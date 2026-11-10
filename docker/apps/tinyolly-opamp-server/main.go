// TinyOlly OpAMP Server
// Manages OpenTelemetry Collector configuration via OpAMP protocol
// Exposes REST API for TinyOlly UI integration

package main

import (
	"context"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"mime"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"sync"
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
	InstanceID      string           `json:"instance_id"`
	AgentType       string           `json:"agent_type"`
	AgentVersion    string           `json:"agent_version"`
	EffectiveConfig string           `json:"effective_config"`
	LastSeen        time.Time        `json:"last_seen"`
	Status          string           `json:"status"`
	conn            types.Connection `json:"-"`
}

// OpAMPServer wraps the OpAMP server with REST API
type OpAMPServer struct {
	opampServer    server.OpAMPServer
	agents         map[string]*AgentState      // keyed by instance ID
	connToAgent    map[types.Connection]string // maps connection to instance ID
	agentsMu       sync.RWMutex
	pendingConfigs map[string]string // instanceID -> pending config
	configMu       sync.RWMutex
	currentConfig  string
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
		pendingConfigs: make(map[string]string),
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
	// Extract instance ID from the message
	instanceID := ""
	if len(msg.InstanceUid) > 0 {
		instanceID = hex.EncodeToString(msg.InstanceUid)
	}

	if instanceID == "" {
		log.Printf("Received message without instance ID")
		return &protobufs.ServerToAgent{}
	}

	s.agentsMu.Lock()

	// Find or create agent
	agent, exists := s.agents[instanceID]
	if !exists {
		agent = &AgentState{
			InstanceID: instanceID,
			AgentType:  "otel-collector",
			Status:     "connected",
			conn:       conn,
		}
		s.agents[instanceID] = agent
		s.connToAgent[conn] = instanceID
		log.Printf("New agent registered: %s", instanceID)
	}

	agent.LastSeen = time.Now()
	agent.Status = "connected"
	agent.conn = conn

	// Extract agent description
	if msg.AgentDescription != nil {
		for _, attr := range msg.AgentDescription.IdentifyingAttributes {
			if attr.Key == "service.name" {
				agent.AgentType = attr.Value.GetStringValue()
			}
			if attr.Key == "service.version" {
				agent.AgentVersion = attr.Value.GetStringValue()
			}
		}
	}

	// Extract effective config
	if msg.EffectiveConfig != nil && msg.EffectiveConfig.ConfigMap != nil {
		for _, configBody := range msg.EffectiveConfig.ConfigMap.ConfigMap {
			agent.EffectiveConfig = string(configBody.Body)
			break
		}
	}

	s.agentsMu.Unlock()

	// Check if there's a pending config for this agent
	s.configMu.Lock()
	pendingConfig, hasPending := s.pendingConfigs[instanceID]
	if hasPending {
		delete(s.pendingConfigs, instanceID)
	}
	s.configMu.Unlock()

	response := &protobufs.ServerToAgent{}

	if hasPending {
		log.Printf("Sending pending config to agent %s", instanceID)
		response.RemoteConfig = &protobufs.AgentRemoteConfig{
			Config: &protobufs.AgentConfigMap{
				ConfigMap: map[string]*protobufs.AgentConfigObject{
					"": {Body: []byte(pendingConfig)},
				},
			},
			ConfigHash: []byte(fmt.Sprintf("%d", time.Now().UnixNano())),
		}
	}

	return response
}

// onConnectionClose handles disconnections
func (s *OpAMPServer) onConnectionClose(conn types.Connection) {
	s.agentsMu.Lock()
	defer s.agentsMu.Unlock()

	if instanceID, exists := s.connToAgent[conn]; exists {
		if agent, ok := s.agents[instanceID]; ok {
			agent.Status = "disconnected"
			agent.LastSeen = time.Now()
			log.Printf("Agent disconnected: %s", instanceID)
		}
		delete(s.connToAgent, conn)
	}
}

// REST API Types

type StatusResponse struct {
	Status     string                 `json:"status"`
	AgentCount int                    `json:"agent_count"`
	Agents     map[string]*AgentState `json:"agents"`
}

type ConfigUpdateRequest struct {
	Config     string `json:"config"`
	InstanceID string `json:"instance_id,omitempty"`
}

type ConfigUpdateResponse struct {
	Status      string   `json:"status"`
	Message     string   `json:"message"`
	AffectedIDs []string `json:"affected_instance_ids"`
}

// REST Handlers

func (s *OpAMPServer) handleStatus(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	s.agentsMu.RLock()
	agentsCopy := make(map[string]*AgentState)
	for k, v := range s.agents {
		agentsCopy[k] = v
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

	s.agentsMu.RLock()
	defer s.agentsMu.RUnlock()

	if instanceID != "" {
		if agent, exists := s.agents[instanceID]; exists {
			w.Header().Set("Content-Type", "application/json")
			json.NewEncoder(w).Encode(map[string]interface{}{
				"instance_id": instanceID,
				"config":      agent.EffectiveConfig,
				"status":      agent.Status,
			})
			return
		}
		http.Error(w, "Agent not found", http.StatusNotFound)
		return
	}

	// Return first connected agent's config
	for _, agent := range s.agents {
		if agent.Status == "connected" {
			w.Header().Set("Content-Type", "application/json")
			json.NewEncoder(w).Encode(map[string]interface{}{
				"instance_id": agent.InstanceID,
				"config":      agent.EffectiveConfig,
				"status":      agent.Status,
			})
			return
		}
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"config": s.getCurrentConfig(),
		"status": "no_agents_connected",
	})
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

	s.setCurrentConfig(req.Config)

	s.agentsMu.RLock()
	affectedIDs := []string{} // Initialize as empty slice, not nil, so JSON marshals to [] not null

	if req.InstanceID != "" {
		if _, exists := s.agents[req.InstanceID]; exists {
			affectedIDs = append(affectedIDs, req.InstanceID)
		}
	} else {
		for id, agent := range s.agents {
			if agent.Status == "connected" {
				affectedIDs = append(affectedIDs, id)
			}
		}
	}
	s.agentsMu.RUnlock()

	s.configMu.Lock()
	for _, id := range affectedIDs {
		s.pendingConfigs[id] = req.Config
		log.Printf("Queued config update for agent %s", id)
	}
	s.configMu.Unlock()

	response := ConfigUpdateResponse{
		Status:      "pending",
		Message:     fmt.Sprintf("Config update queued for %d agent(s)", len(affectedIDs)),
		AffectedIDs: affectedIDs,
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
			s.handleUpdateConfig(w, r)
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
	ctx := context.Background()

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
			log.Fatalf("Failed to start OpAMP server: %v", err)
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

	if err := httpServer.ListenAndServe(); err != nil {
		log.Fatalf("Failed to start HTTP server: %v", err)
	}
}
