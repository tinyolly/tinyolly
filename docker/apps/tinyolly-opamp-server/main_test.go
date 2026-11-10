package main

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
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
