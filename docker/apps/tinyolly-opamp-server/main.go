// TinyOlly OpAMP Server
// Manages OpenTelemetry Collector configuration via OpAMP protocol
// Exposes REST API for TinyOlly UI integration

package main

import (
	"context"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"mime"
	"net/http"
	"net/url"
	"os"
	"os/signal"
	"path/filepath"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/open-telemetry/opamp-go/protobufs"
	"github.com/open-telemetry/opamp-go/server"
	"github.com/open-telemetry/opamp-go/server/types"
	"go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracehttp"
	"go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	semconv "go.opentelemetry.io/otel/semconv/v1.26.0"
	"go.opentelemetry.io/otel/trace"
)

var tracer trace.Tracer

// AgentState tracks the state of a connected OTel Collector agent
type AgentState struct {
	InstanceID      string    `json:"instance_id"`
	AgentType       string    `json:"agent_type"`
	AgentVersion    string    `json:"agent_version"`
	EffectiveConfig string    `json:"effective_config"`
	LastSeen        time.Time `json:"last_seen"`
	Status          string    `json:"status"`
	// Remote-config delivery tracking: "", "pending" (queued/sent), "applying", "applied", "failed".
	ConfigStatus      string `json:"config_status,omitempty"`
	ConfigError       string `json:"config_error,omitempty"`
	AppliedConfigHash string `json:"applied_config_hash,omitempty"`

	conn       types.Connection // current connection (a reconnect replaces it)
	sentHash   string           // hash of the config last sent on the current connection
	failedHash string           // hash the agent reported FAILED for; not re-sent until re-POSTed
}

// remoteConfig is a config body with its content hash (sha256, hex).
type remoteConfig struct {
	body string
	hash string
}

func newRemoteConfig(body string) *remoteConfig {
	sum := sha256.Sum256([]byte(body))
	return &remoteConfig{body: body, hash: hex.EncodeToString(sum[:])}
}

// OpAMPServer wraps the OpAMP server with REST API
type OpAMPServer struct {
	opampServer server.OpAMPServer
	agents      map[string]*AgentState      // keyed by instance ID
	connToAgent map[types.Connection]string // maps connection to instance ID
	agentsMu    sync.RWMutex                // lock order: agentsMu before configMu

	configMu       sync.RWMutex
	pendingConfigs map[string]*remoteConfig // instanceID -> config from a targeted POST
	fleetConfig    *remoteConfig            // config from a fleet-wide POST; offered to every agent, incl. new/reconnecting ones
	currentConfig  string                   // what GET /config shows when no agent is connected

	apiToken string // optional bearer token required for writes (OPAMP_API_TOKEN)
}

// maxConfigBodyBytes caps the size of a POST /config body.
const maxConfigBodyBytes = 1 << 20 // 1 MiB

func (s *OpAMPServer) getCurrentConfig() string {
	s.configMu.RLock()
	defer s.configMu.RUnlock()
	return s.currentConfig
}

func (s *OpAMPServer) setCurrentConfig(cfg string) {
	s.configMu.Lock()
	defer s.configMu.Unlock()
	s.currentConfig = cfg
}

// NewOpAMPServer creates a new OpAMP server instance
func NewOpAMPServer() *OpAMPServer {
	s := &OpAMPServer{
		agents:         make(map[string]*AgentState),
		connToAgent:    make(map[types.Connection]string),
		pendingConfigs: make(map[string]*remoteConfig),
		apiToken:       os.Getenv("OPAMP_API_TOKEN"),
	}
	s.loadInitialConfig()
	return s
}

// loadInitialConfig attempts to load the default collector config from file
func (s *OpAMPServer) loadInitialConfig() {
	configPaths := []string{
		"/etc/otel-collector-config.yaml",
		"./otelcol-configs/config.yaml",
		"../otelcol-configs/config.yaml",
	}

	if configPath := os.Getenv("COLLECTOR_CONFIG_PATH"); configPath != "" {
		configPaths = append([]string{configPath}, configPaths...)
	}

	for _, path := range configPaths {
		if absPath, err := filepath.Abs(path); err == nil {
			if data, err := os.ReadFile(absPath); err == nil {
				s.currentConfig = string(data)
				log.Printf("Loaded initial config from %s", absPath)
				return
			}
		}
	}

	s.currentConfig = defaultConfig
	log.Printf("Using default config (no config file found)")
}

// OnConnecting handles new connections
func (s *OpAMPServer) OnConnecting(request *http.Request) types.ConnectionResponse {
	log.Printf("Agent connecting from %s", request.RemoteAddr)
	return types.ConnectionResponse{
		Accept: true,
		ConnectionCallbacks: types.ConnectionCallbacks{
			OnConnected:       s.onConnected,
			OnMessage:         s.onMessage,
			OnConnectionClose: s.onConnectionClose,
		},
	}
}

// onConnected is called when a connection is established
func (s *OpAMPServer) onConnected(ctx context.Context, conn types.Connection) {
	log.Printf("Agent connected")
}

// onMessage handles messages from agents
func (s *OpAMPServer) onMessage(ctx context.Context, conn types.Connection, msg *protobufs.AgentToServer) *protobufs.ServerToAgent {
	return s.handleAgentMessage(conn, msg)
}

const serverCapabilities = uint64(protobufs.ServerCapabilities_ServerCapabilities_AcceptsStatus |
	protobufs.ServerCapabilities_ServerCapabilities_OffersRemoteConfig |
	protobufs.ServerCapabilities_ServerCapabilities_AcceptsEffectiveConfig)

func (s *OpAMPServer) handleAgentMessage(conn types.Connection, msg *protobufs.AgentToServer) *protobufs.ServerToAgent {
	if len(msg.InstanceUid) == 0 {
		log.Printf("Received message without instance ID")
		return &protobufs.ServerToAgent{}
	}
	instanceID := hex.EncodeToString(msg.InstanceUid)

	response := &protobufs.ServerToAgent{InstanceUid: msg.InstanceUid, Capabilities: serverCapabilities}

	s.agentsMu.Lock()
	defer s.agentsMu.Unlock()

	agent, exists := s.agents[instanceID]
	if !exists {
		agent = &AgentState{InstanceID: instanceID, AgentType: "otel-collector"}
		s.agents[instanceID] = agent
		log.Printf("New agent registered: %s", instanceID)
	}

	// (Re)bind the connection on EVERY message: after a reconnect the new connection must map to the agent,
	// and the old one must stop mapping (its later close must not mark the live agent disconnected).
	if agent.conn != conn {
		if agent.conn != nil {
			delete(s.connToAgent, agent.conn)
		}
		agent.conn = conn
		agent.sentHash = "" // a new connection has not been sent anything yet
	}
	s.connToAgent[conn] = instanceID

	agent.LastSeen = time.Now()
	agent.Status = "connected"

	if msg.AgentDescription != nil {
		for _, attr := range msg.AgentDescription.IdentifyingAttributes {
			if attr.Key == "service.name" {
				agent.AgentType = attr.Value.GetStringValue()
			}
			if attr.Key == "service.version" {
				agent.AgentVersion = attr.Value.GetStringValue()
			}
		}
	} else if !exists || agent.AgentVersion == "" {
		// We know nothing about this agent yet (new, or the server restarted): ask for its full state.
		response.Flags |= uint64(protobufs.ServerToAgentFlags_ServerToAgentFlags_ReportFullState)
	}

	if msg.EffectiveConfig != nil && msg.EffectiveConfig.ConfigMap != nil {
		for _, configBody := range msg.EffectiveConfig.ConfigMap.ConfigMap {
			agent.EffectiveConfig = string(configBody.Body)
			break
		}
	}

	if rcs := msg.RemoteConfigStatus; rcs != nil && len(rcs.LastRemoteConfigHash) > 0 {
		s.recordConfigStatus(agent, hex.EncodeToString(rcs.LastRemoteConfigHash), rcs)
	}

	if cfg := s.configFor(instanceID); cfg != nil &&
		agent.AppliedConfigHash != cfg.hash && agent.failedHash != cfg.hash && agent.sentHash != cfg.hash {
		log.Printf("Sending config %s to agent %s", cfg.hash[:12], instanceID)
		agent.sentHash = cfg.hash
		if agent.ConfigStatus != "applying" {
			agent.ConfigStatus = "pending"
		}
		response.RemoteConfig = &protobufs.AgentRemoteConfig{
			Config: &protobufs.AgentConfigMap{
				ConfigMap: map[string]*protobufs.AgentConfigObject{"": {Body: []byte(cfg.body)}},
			},
			ConfigHash: []byte(cfg.hash),
		}
	}
	return response
}

// recordConfigStatus updates delivery tracking from the agent's RemoteConfigStatus. The hash the agent echoes
// back is the ConfigHash we sent (the hex string's bytes), so compare against both forms.
func (s *OpAMPServer) recordConfigStatus(agent *AgentState, echoed string, rcs *protobufs.RemoteConfigStatus) {
	hash := string(rcs.LastRemoteConfigHash) // we send the hex string as the hash bytes
	if len(hash) != sha256.Size*2 {
		hash = echoed
	}
	switch rcs.Status {
	case protobufs.RemoteConfigStatuses_RemoteConfigStatuses_APPLIED:
		agent.ConfigStatus, agent.ConfigError, agent.AppliedConfigHash = "applied", "", hash
		s.configMu.Lock()
		if p, ok := s.pendingConfigs[agent.InstanceID]; ok && p.hash == hash {
			delete(s.pendingConfigs, agent.InstanceID)
		}
		s.configMu.Unlock()
	case protobufs.RemoteConfigStatuses_RemoteConfigStatuses_APPLYING:
		agent.ConfigStatus = "applying"
	case protobufs.RemoteConfigStatuses_RemoteConfigStatuses_FAILED:
		agent.ConfigStatus, agent.ConfigError, agent.failedHash = "failed", rcs.ErrorMessage, hash
		log.Printf("Agent %s failed to apply config %.12s: %s", agent.InstanceID, hash, rcs.ErrorMessage)
	}
}

// configFor returns the config that should be on this agent: a targeted one if queued, else the fleet one.
func (s *OpAMPServer) configFor(instanceID string) *remoteConfig {
	s.configMu.RLock()
	defer s.configMu.RUnlock()
	if p, ok := s.pendingConfigs[instanceID]; ok {
		return p
	}
	return s.fleetConfig
}

// onConnectionClose handles disconnections
func (s *OpAMPServer) onConnectionClose(conn types.Connection) {
	s.agentsMu.Lock()
	defer s.agentsMu.Unlock()

	instanceID, exists := s.connToAgent[conn]
	if !exists {
		return
	}
	delete(s.connToAgent, conn)
	// Only mark the agent disconnected if THIS was its current connection; a stale connection closing after
	// a reconnect must not flip a live agent to disconnected.
	if agent, ok := s.agents[instanceID]; ok && agent.conn == conn {
		agent.Status = "disconnected"
		agent.LastSeen = time.Now()
		agent.conn = nil
		log.Printf("Agent disconnected: %s", instanceID)
	}
}

// REST API Types

type StatusResponse struct {
	Status     string                `json:"status"`
	AgentCount int                   `json:"agent_count"`
	Agents     map[string]AgentState `json:"agents"`
}

type ConfigUpdateRequest struct {
	Config     string `json:"config"`
	InstanceID string `json:"instance_id,omitempty"`
}

type ConfigUpdateResponse struct {
	Status      string   `json:"status"`
	Message     string   `json:"message"`
	AffectedIDs []string `json:"affected_instance_ids"`
	ConfigHash  string   `json:"config_hash"` // sha256 of the config; agents echo it back when applied (see /status)
}

// REST Handlers

func (s *OpAMPServer) handleStatus(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	// Snapshot by value under the lock: encoding live pointers after unlocking raced with onMessage.
	s.agentsMu.RLock()
	agentsCopy := make(map[string]AgentState, len(s.agents))
	for k, v := range s.agents {
		agentsCopy[k] = *v
	}
	s.agentsMu.RUnlock()

	response := StatusResponse{
		Status:     "ok",
		AgentCount: len(agentsCopy),
		Agents:     agentsCopy,
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(response)
}

func (s *OpAMPServer) handleGetConfig(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	instanceID := r.URL.Query().Get("instance_id")

	// Copy what we need under the lock, then write the response without holding it
	// (a slow client used to block every agent message while the lock was held across the write).
	var out map[string]interface{}
	found := false
	s.agentsMu.RLock()
	if instanceID != "" {
		if agent, exists := s.agents[instanceID]; exists {
			found = true
			out = map[string]interface{}{
				"instance_id":   instanceID,
				"config":        agent.EffectiveConfig,
				"status":        agent.Status,
				"config_status": agent.ConfigStatus,
				"config_error":  agent.ConfigError,
			}
		}
	} else {
		for _, agent := range s.agents { // first connected agent
			if agent.Status == "connected" {
				found = true
				out = map[string]interface{}{
					"instance_id":   agent.InstanceID,
					"config":        agent.EffectiveConfig,
					"status":        agent.Status,
					"config_status": agent.ConfigStatus,
					"config_error":  agent.ConfigError,
				}
				break
			}
		}
	}
	s.agentsMu.RUnlock()

	if instanceID != "" && !found {
		http.Error(w, "Agent not found", http.StatusNotFound)
		return
	}
	if !found {
		out = map[string]interface{}{"config": s.getCurrentConfig(), "status": "no_agents_connected"}
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(out)
}

func (s *OpAMPServer) handleUpdateConfig(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost && r.Method != http.MethodPut {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	// Require a JSON content type. Browsers can send text/plain cross-origin without a CORS preflight, so
	// rejecting anything else stops a web page the user visits from posting a config to this API.
	if mediaType, _, err := mime.ParseMediaType(r.Header.Get("Content-Type")); err != nil || mediaType != "application/json" {
		http.Error(w, "Content-Type must be application/json", http.StatusUnsupportedMediaType)
		return
	}

	r.Body = http.MaxBytesReader(w, r.Body, maxConfigBodyBytes)
	var req ConfigUpdateRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		var tooLarge *http.MaxBytesError
		if errors.As(err, &tooLarge) {
			http.Error(w, "Config too large", http.StatusRequestEntityTooLarge)
			return
		}
		http.Error(w, "Invalid JSON: "+err.Error(), http.StatusBadRequest)
		return
	}

	if strings.TrimSpace(req.Config) == "" {
		http.Error(w, "Config is required", http.StatusBadRequest)
		return
	}

	cfg := newRemoteConfig(req.Config)
	affectedIDs := []string{} // empty slice, not nil, so JSON marshals to [] not null

	s.agentsMu.Lock()
	if req.InstanceID != "" {
		agent, exists := s.agents[req.InstanceID]
		if !exists {
			s.agentsMu.Unlock()
			http.Error(w, "Unknown instance_id", http.StatusNotFound)
			return
		}
		// Targeted update: queue it for that agent only. It must not replace the fleet-wide config.
		s.configMu.Lock()
		s.pendingConfigs[req.InstanceID] = cfg
		s.configMu.Unlock()
		resetDelivery(agent)
		affectedIDs = append(affectedIDs, req.InstanceID)
	} else {
		// Fleet update: remembered, so agents that connect or reconnect later get it too.
		s.configMu.Lock()
		s.fleetConfig = cfg
		s.pendingConfigs = make(map[string]*remoteConfig) // a fleet config supersedes older targeted ones
		s.currentConfig = req.Config
		s.configMu.Unlock()
		for id, agent := range s.agents {
			resetDelivery(agent)
			if agent.Status == "connected" {
				affectedIDs = append(affectedIDs, id)
			}
		}
	}
	s.agentsMu.Unlock()

	response := ConfigUpdateResponse{
		Status:      "pending",
		Message:     fmt.Sprintf("Config update queued for %d connected agent(s); other agents get it when they connect", len(affectedIDs)),
		AffectedIDs: affectedIDs,
		ConfigHash:  cfg.hash,
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(response)
}

func (s *OpAMPServer) handleHealth(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{"status": "healthy"})
}

const defaultConfig = `receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

extensions:
  opamp:
    server:
      ws:
        endpoint: ws://tinyolly-opamp-server:4320/v1/opamp

processors:
  batch:
    timeout: 1s
    send_batch_size: 1024

exporters:
  debug:
    verbosity: detailed

  otlp:
    endpoint: "tinyolly-otlp-receiver:4343"
    tls:
      insecure: true

service:
  extensions: [opamp]
  pipelines:
    traces:
      receivers: [otlp]
      processors: [batch]
      exporters: [debug, otlp]

    metrics:
      receivers: [otlp]
      processors: [batch]
      exporters: [debug, otlp]

    logs:
      receivers: [otlp]
      processors: [batch]
      exporters: [debug, otlp]
`

// parseOTLPEndpoint turns OTEL_EXPORTER_OTLP_ENDPOINT into the host:port the exporter wants and whether the
// connection is plaintext. Accepts "http://host:4318", "https://host:4318" and a bare "host:4318" (plaintext).
func parseOTLPEndpoint(raw string) (host string, insecure bool, err error) {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return "", false, errors.New("empty OTLP endpoint")
	}
	if !strings.Contains(raw, "://") {
		raw = "http://" + raw
	}
	u, err := url.Parse(raw)
	if err != nil || u.Host == "" {
		return "", false, fmt.Errorf("invalid OTLP endpoint %q", raw)
	}
	switch u.Scheme {
	case "http":
		return u.Host, true, nil
	case "https":
		return u.Host, false, nil
	default:
		return "", false, fmt.Errorf("unsupported OTLP endpoint scheme %q", u.Scheme)
	}
}

// routes builds the REST API mux.
func (s *OpAMPServer) routes() *http.ServeMux {
	mux := http.NewServeMux()
	mux.HandleFunc("/health", s.handleHealth)
	mux.HandleFunc("/status", s.handleStatus)
	mux.HandleFunc("/config", func(w http.ResponseWriter, r *http.Request) {
		switch r.Method {
		case http.MethodGet:
			s.handleGetConfig(w, r)
		case http.MethodPost, http.MethodPut:
			s.requireToken(s.handleUpdateConfig)(w, r)
		default:
			http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		}
	})
	return mux
}

// initTelemetry sets up OpenTelemetry tracing
func initTelemetry(ctx context.Context) (func(context.Context) error, error) {
	// Get OTLP endpoint from environment
	endpoint := os.Getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
	if endpoint == "" {
		endpoint = "http://otel-collector:4318"
	}

	// Create OTLP trace exporter
	host, insecure, err := parseOTLPEndpoint(endpoint)
	if err != nil {
		return nil, err
	}
	opts := []otlptracehttp.Option{otlptracehttp.WithEndpoint(host)}
	if insecure {
		opts = append(opts, otlptracehttp.WithInsecure())
	}
	exporter, err := otlptracehttp.New(ctx, opts...)
	if err != nil {
		return nil, fmt.Errorf("failed to create trace exporter: %w", err)
	}

	// Create resource with service name
	serviceName := os.Getenv("OTEL_SERVICE_NAME")
	if serviceName == "" {
		serviceName = "tinyolly-opamp-server"
	}

	res, err := resource.New(ctx,
		resource.WithAttributes(
			semconv.ServiceName(serviceName),
			semconv.ServiceVersion("1.0.0"),
		),
	)
	if err != nil {
		return nil, fmt.Errorf("failed to create resource: %w", err)
	}

	// Create trace provider
	tp := sdktrace.NewTracerProvider(
		sdktrace.WithBatcher(exporter),
		sdktrace.WithResource(res),
	)

	otel.SetTracerProvider(tp)
	tracer = tp.Tracer("tinyolly-opamp-server")

	log.Printf("OpenTelemetry tracing initialized, exporting to %s", endpoint)

	return tp.Shutdown, nil
}

func main() {
	os.Exit(run())
}

func run() int {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	// Initialize OpenTelemetry
	shutdown, err := initTelemetry(ctx)
	if err != nil {
		log.Printf("Warning: Failed to initialize telemetry: %v", err)
	} else {
		defer func() {
			if err := shutdown(ctx); err != nil {
				log.Printf("Error shutting down telemetry: %v", err)
			}
		}()
	}

	opampPort := os.Getenv("OPAMP_PORT")
	if opampPort == "" {
		opampPort = "4320"
	}

	httpPort := os.Getenv("HTTP_PORT")
	if httpPort == "" {
		httpPort = "4321"
	}

	s := NewOpAMPServer()

	// Create OpAMP server
	s.opampServer = server.New(nil) // nil logger uses default

	errCh := make(chan error, 2)

	// Start OpAMP server in goroutine
	go func() {
		settings := server.StartSettings{
			Settings: server.Settings{
				Callbacks: types.Callbacks{
					OnConnecting: s.OnConnecting,
				},
			},
			ListenEndpoint: fmt.Sprintf("0.0.0.0:%s", opampPort),
		}

		log.Printf("Starting OpAMP WebSocket server on port %s", opampPort)
		if err := s.opampServer.Start(settings); err != nil {
			errCh <- fmt.Errorf("failed to start OpAMP server: %w", err)
		}
	}()

	// Setup HTTP REST API with OpenTelemetry instrumentation. No CORS headers are sent: the only legitimate
	// client is the TinyOlly UI server, which calls this API server-side, never from a browser.
	handler := otelhttp.NewHandler(s.routes(), "tinyolly-opamp-server")

	httpServer := &http.Server{
		Addr:              fmt.Sprintf(":%s", httpPort),
		Handler:           handler,
		ReadHeaderTimeout: 10 * time.Second,
		ReadTimeout:       30 * time.Second,
		WriteTimeout:      30 * time.Second,
		IdleTimeout:       60 * time.Second,
	}

	log.Printf("Starting HTTP REST API on port %s", httpPort)
	log.Printf("Endpoints:")
	log.Printf("  GET  /health - Health check")
	log.Printf("  GET  /status - Get connected agents status")
	log.Printf("  GET  /config - Get current collector config")
	log.Printf("  POST /config - Update collector config")

	go func() {
		if err := httpServer.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			errCh <- fmt.Errorf("failed to start HTTP server: %w", err)
		}
	}()

	code := 0
	select {
	case <-ctx.Done():
		log.Printf("Shutting down...")
	case err := <-errCh:
		log.Printf("Fatal: %v", err)
		code = 1
	}

	shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := httpServer.Shutdown(shutdownCtx); err != nil {
		log.Printf("HTTP shutdown: %v", err)
	}
	if err := s.opampServer.Stop(shutdownCtx); err != nil {
		log.Printf("OpAMP shutdown: %v", err)
	}
	return code // deferred telemetry shutdown runs now (log.Fatalf used to skip it)
}

// resetDelivery lets a (re-)POSTed config be sent again even if an identical one failed or was sent before.
func resetDelivery(agent *AgentState) {
	agent.sentHash, agent.failedHash = "", ""
	agent.ConfigStatus, agent.ConfigError = "pending", ""
}

// requireToken protects the write endpoints with OPAMP_API_TOKEN when it is set (unset = open, as before:
// the API is only meant to be reachable by the TinyOlly UI on the private network).
func (s *OpAMPServer) requireToken(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if s.apiToken != "" {
			got := strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer ")
			if subtle.ConstantTimeCompare([]byte(got), []byte(s.apiToken)) != 1 {
				http.Error(w, "Unauthorized", http.StatusUnauthorized)
				return
			}
		}
		next(w, r)
	}
}
