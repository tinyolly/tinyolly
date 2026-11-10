package main

import (
	"context"
	"encoding/hex"
	"encoding/json"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"

	"github.com/open-telemetry/opamp-go/protobufs"
)

func newTestServer() (*OpAMPServer, http.Handler) {
	s := NewOpAMPServer()
	s.currentConfig = "initial: true\n"
	return s, s.routes()
}

func do(h http.Handler, method, path, contentType, body string) *httptest.ResponseRecorder {
	req := httptest.NewRequest(method, path, strings.NewReader(body))
	if contentType != "" {
		req.Header.Set("Content-Type", contentType)
	}
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	return rec
}

func TestNoCORSHeaders(t *testing.T) {
	_, h := newTestServer()
	for _, tc := range []struct{ method, path string }{
		{"GET", "/health"}, {"GET", "/config"}, {"GET", "/status"}, {"OPTIONS", "/config"},
	} {
		rec := do(h, tc.method, tc.path, "", "")
		for k := range rec.Header() {
			if strings.HasPrefix(k, "Access-Control-") {
				t.Errorf("%s %s sent %s; the API must not be readable/writable cross-origin", tc.method, tc.path, k)
			}
		}
	}
	if rec := do(h, "OPTIONS", "/config", "", ""); rec.Code == http.StatusOK {
		t.Errorf("OPTIONS preflight must not succeed, got %d", rec.Code)
	}
}

func TestPostConfigRequiresJSONContentType(t *testing.T) {
	s, h := newTestServer()
	body := `{"config":"receivers: {}\n"}`
	for _, ct := range []string{"", "text/plain", "application/x-www-form-urlencoded", "text/plain;charset=UTF-8"} {
		rec := do(h, "POST", "/config", ct, body)
		if rec.Code != http.StatusUnsupportedMediaType {
			t.Errorf("Content-Type %q: got %d, want 415 (a cross-origin page can send text/plain without a preflight)", ct, rec.Code)
		}
	}
	if got := s.getCurrentConfig(); got != "initial: true\n" {
		t.Errorf("config was changed by a rejected request: %q", got)
	}
	rec := do(h, "POST", "/config", "application/json; charset=utf-8", body)
	if rec.Code != http.StatusOK {
		t.Fatalf("valid request: got %d: %s", rec.Code, rec.Body.String())
	}
	if got := s.getCurrentConfig(); got != "receivers: {}\n" {
		t.Errorf("config not stored: %q", got)
	}
}

func TestPostConfigRejectsOversizedAndEmpty(t *testing.T) {
	_, h := newTestServer()
	big := `{"config":"` + strings.Repeat("a", maxConfigBodyBytes+10) + `"}`
	if rec := do(h, "POST", "/config", "application/json", big); rec.Code != http.StatusRequestEntityTooLarge {
		t.Errorf("oversized body: got %d, want 413", rec.Code)
	}
	for _, body := range []string{`{"config":""}`, `{"config":"   \n"}`, `{}`} {
		if rec := do(h, "POST", "/config", "application/json", body); rec.Code != http.StatusBadRequest {
			t.Errorf("body %s: got %d, want 400", body, rec.Code)
		}
	}
	if rec := do(h, "POST", "/config", "application/json", `{not json`); rec.Code != http.StatusBadRequest {
		t.Errorf("invalid JSON: got %d, want 400", rec.Code)
	}
}

// Run with -race: concurrent POST and GET of the fleet config must not race.
func TestCurrentConfigIsRaceFree(t *testing.T) {
	_, h := newTestServer()
	var wg sync.WaitGroup
	for i := 0; i < 20; i++ {
		wg.Add(2)
		go func() {
			defer wg.Done()
			do(h, "POST", "/config", "application/json", `{"config":"a: 1\n"}`)
		}()
		go func() {
			defer wg.Done()
			do(h, "GET", "/config", "", "")
		}()
	}
	wg.Wait()
}

func TestParseOTLPEndpoint(t *testing.T) {
	cases := []struct {
		in       string
		host     string
		insecure bool
		wantErr  bool
	}{
		{"http://otel-collector:4318", "otel-collector:4318", true, false},
		{"https://collector.example.com:4318", "collector.example.com:4318", false, false},
		{"otel:4318", "otel:4318", true, false}, // shorter than 7 chars used to panic; no scheme used to be mangled
		{"a:4318", "a:4318", true, false},
		{"  http://x:1  ", "x:1", true, false},
		{"", "", false, true},
		{"ftp://x:1", "", false, true},
		{"http://", "", false, true},
	}
	for _, tc := range cases {
		host, insecure, err := parseOTLPEndpoint(tc.in)
		if (err != nil) != tc.wantErr {
			t.Errorf("%q: err=%v, wantErr=%v", tc.in, err, tc.wantErr)
			continue
		}
		if err == nil && (host != tc.host || insecure != tc.insecure) {
			t.Errorf("%q: got (%q, %v), want (%q, %v)", tc.in, host, insecure, tc.host, tc.insecure)
		}
	}
}

// ---- agent lifecycle / config delivery -------------------------------------------------------------------

type fakeConn struct{ id int }

func (c *fakeConn) Connection() net.Conn                                       { return nil }
func (c *fakeConn) Send(ctx context.Context, m *protobufs.ServerToAgent) error { return nil }
func (c *fakeConn) Disconnect() error                                          { return nil }

func msgFrom(id byte, extra func(*protobufs.AgentToServer)) *protobufs.AgentToServer {
	m := &protobufs.AgentToServer{InstanceUid: []byte{id, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15}}
	if extra != nil {
		extra(m)
	}
	return m
}

func hexID(id byte) string { return hex.EncodeToString(msgFrom(id, nil).InstanceUid) }

func postConfig(t *testing.T, h http.Handler, cfg, instance string) *httptest.ResponseRecorder {
	t.Helper()
	body, _ := json.Marshal(ConfigUpdateRequest{Config: cfg, InstanceID: instance})
	return do(h, "POST", "/config", "application/json", string(body))
}

func status(t *testing.T, h http.Handler, id string) AgentState {
	t.Helper()
	var resp StatusResponse
	if err := json.Unmarshal(do(h, "GET", "/status", "", "").Body.Bytes(), &resp); err != nil {
		t.Fatal(err)
	}
	return resp.Agents[id]
}

func TestReconnectRemapsConnection(t *testing.T) {
	s, h := newTestServer()
	c1, c2 := &fakeConn{1}, &fakeConn{2}
	s.handleAgentMessage(c1, msgFrom(1, nil))
	s.handleAgentMessage(c2, msgFrom(1, nil)) // same agent, new connection
	if len(s.connToAgent) != 1 || s.connToAgent[c2] != hexID(1) {
		t.Fatalf("connToAgent should map only the new connection: %v", s.connToAgent)
	}
	s.onConnectionClose(c1) // stale connection closing must not flip the live agent
	if st := status(t, h, hexID(1)).Status; st != "connected" {
		t.Fatalf("live agent marked %q after stale close", st)
	}
	s.onConnectionClose(c2)
	if st := status(t, h, hexID(1)).Status; st != "disconnected" {
		t.Fatalf("agent should be disconnected, got %q", st)
	}
}

func TestFleetConfigReachesAgentsConnectingLater(t *testing.T) {
	s, h := newTestServer()
	if rec := postConfig(t, h, "fleet: 1\n", ""); rec.Code != 200 {
		t.Fatal(rec.Body.String())
	}
	c := &fakeConn{1}
	resp := s.handleAgentMessage(c, msgFrom(7, nil)) // never seen before the POST
	if resp.RemoteConfig == nil || string(resp.RemoteConfig.Config.ConfigMap[""].Body) != "fleet: 1\n" {
		t.Fatalf("new agent did not receive the fleet config: %+v", resp.RemoteConfig)
	}
	if want := newRemoteConfig("fleet: 1\n").hash; string(resp.RemoteConfig.ConfigHash) != want {
		t.Fatalf("ConfigHash must be the content hash, got %q want %q", resp.RemoteConfig.ConfigHash, want)
	}
	// not re-sent on the next message of the same connection
	if again := s.handleAgentMessage(c, msgFrom(7, nil)); again.RemoteConfig != nil {
		t.Fatal("config re-sent on the same connection before an ack")
	}
}

func TestTargetedPostDoesNotChangeFleetConfigAndUnknownIs404(t *testing.T) {
	s, h := newTestServer()
	s.handleAgentMessage(&fakeConn{1}, msgFrom(1, nil))
	if rec := postConfig(t, h, "only: one\n", hexID(1)); rec.Code != 200 {
		t.Fatal(rec.Body.String())
	}
	if s.fleetConfig != nil || s.getCurrentConfig() != "initial: true\n" {
		t.Fatalf("targeted POST must not overwrite fleet/current config (fleet=%v current=%q)", s.fleetConfig, s.getCurrentConfig())
	}
	if rec := postConfig(t, h, "x: 1\n", "does-not-exist"); rec.Code != http.StatusNotFound {
		t.Fatalf("unknown instance_id should be 404, got %d", rec.Code)
	}
	// another agent does not get the targeted config
	if resp := s.handleAgentMessage(&fakeConn{2}, msgFrom(2, nil)); resp.RemoteConfig != nil {
		t.Fatal("agent 2 received a config targeted at agent 1")
	}
}

func TestAckAndFailureTracking(t *testing.T) {
	s, h := newTestServer()
	c := &fakeConn{1}
	s.handleAgentMessage(c, msgFrom(1, nil))
	postConfig(t, h, "v: 1\n", "")
	hash := newRemoteConfig("v: 1\n").hash

	first := s.handleAgentMessage(c, msgFrom(1, nil))
	if first.RemoteConfig == nil {
		t.Fatal("config not delivered")
	}
	if second := s.handleAgentMessage(c, msgFrom(1, nil)); second.RemoteConfig != nil {
		t.Fatal("same config re-sent on the same connection before any ack")
	}
	report := func(st protobufs.RemoteConfigStatuses, errMsg string) func(*protobufs.AgentToServer) {
		return func(m *protobufs.AgentToServer) {
			m.RemoteConfigStatus = &protobufs.RemoteConfigStatus{LastRemoteConfigHash: []byte(hash), Status: st, ErrorMessage: errMsg}
		}
	}
	s.handleAgentMessage(c, msgFrom(1, report(protobufs.RemoteConfigStatuses_RemoteConfigStatuses_APPLYING, "")))
	if got := status(t, h, hexID(1)).ConfigStatus; got != "applying" {
		t.Fatalf("want applying, got %q", got)
	}
	s.handleAgentMessage(c, msgFrom(1, report(protobufs.RemoteConfigStatuses_RemoteConfigStatuses_APPLIED, "")))
	st := status(t, h, hexID(1))
	if st.ConfigStatus != "applied" || st.AppliedConfigHash != hash {
		t.Fatalf("want applied/%s, got %+v", hash, st)
	}
	// applied agent reconnecting reports the hash and must not be sent the same config again
	c2 := &fakeConn{2}
	if r := s.handleAgentMessage(c2, msgFrom(1, report(protobufs.RemoteConfigStatuses_RemoteConfigStatuses_APPLIED, ""))); r.RemoteConfig != nil {
		t.Fatal("applied config re-sent after reconnect")
	}

	// a failing config is recorded, not retried in a loop, and can be retried by re-posting it
	postConfig(t, h, "v: 2\n", "")
	bad := newRemoteConfig("v: 2\n").hash
	s.handleAgentMessage(c2, msgFrom(1, nil)) // delivered
	s.handleAgentMessage(c2, msgFrom(1, func(m *protobufs.AgentToServer) {
		m.RemoteConfigStatus = &protobufs.RemoteConfigStatus{LastRemoteConfigHash: []byte(bad), Status: protobufs.RemoteConfigStatuses_RemoteConfigStatuses_FAILED, ErrorMessage: "bad pipeline"}
	}))
	st = status(t, h, hexID(1))
	if st.ConfigStatus != "failed" || st.ConfigError != "bad pipeline" {
		t.Fatalf("failure not recorded: %+v", st)
	}
	if r := s.handleAgentMessage(&fakeConn{3}, msgFrom(1, nil)); r.RemoteConfig != nil {
		t.Fatal("failed config re-sent in a loop")
	}
	postConfig(t, h, "v: 2\n", "")
	if r := s.handleAgentMessage(&fakeConn{3}, msgFrom(1, nil)); r.RemoteConfig == nil {
		t.Fatal("re-POST of a failed config should be retried")
	}
}

func TestFullStateRequestedForUnknownAgent(t *testing.T) {
	s, _ := newTestServer()
	r := s.handleAgentMessage(&fakeConn{1}, msgFrom(1, nil))
	if r.Flags&uint64(protobufs.ServerToAgentFlags_ServerToAgentFlags_ReportFullState) == 0 {
		t.Fatal("server should ask a new agent for its full state")
	}
	if r.Capabilities == 0 || len(r.InstanceUid) == 0 {
		t.Fatal("response should advertise capabilities and echo the instance uid")
	}
}

func TestWriteTokenRequiredWhenSet(t *testing.T) {
	s, h := newTestServer()
	s.apiToken = "s3cret"
	body := `{"config":"a: 1\n"}`
	if rec := do(h, "POST", "/config", "application/json", body); rec.Code != http.StatusUnauthorized {
		t.Fatalf("want 401 without token, got %d", rec.Code)
	}
	req := httptest.NewRequest("POST", "/config", strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer s3cret")
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	if rec.Code != 200 {
		t.Fatalf("want 200 with token, got %d", rec.Code)
	}
}

func TestStatusIsRaceFreeWithMessages(t *testing.T) {
	s, h := newTestServer()
	var wg sync.WaitGroup
	for i := 0; i < 4; i++ {
		wg.Add(2)
		go func(i int) {
			defer wg.Done()
			for j := 0; j < 200; j++ {
				s.handleAgentMessage(&fakeConn{i}, msgFrom(byte(i), nil))
			}
		}(i)
		go func() {
			defer wg.Done()
			for j := 0; j < 200; j++ {
				do(h, "GET", "/status", "", "")
				do(h, "GET", "/config", "", "")
			}
		}()
	}
	wg.Wait()
}
