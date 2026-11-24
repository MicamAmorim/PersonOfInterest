package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"log"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"os/signal"
	"path/filepath"
	"strings"
	"syscall"
	"time"

	"tailscale.com/tsnet"
)

type status struct {
	Login string `json:"login,omitempty"`
	HTTPS string `json:"https,omitempty"`
}

func writeStatus(dir string, state status) error {
	data, err := json.Marshal(state)
	if err != nil {
		return err
	}
	temp := filepath.Join(dir, "status.tmp")
	if err := os.WriteFile(temp, data, 0600); err != nil {
		return err
	}
	return os.Rename(temp, filepath.Join(dir, "status.json"))
}

func run() error {
	dir := flag.String("state", "", "Directory for this node's private state")
	name := flag.String("hostname", "poi-android", "Tailnet hostname")
	backend := flag.String("backend", "http://127.0.0.1:18080", "Local POI address")
	flag.Parse()
	if *dir == "" {
		return errors.New("state directory required")
	}
	target, err := url.Parse(*backend)
	if err != nil || target.Scheme != "http" || target.Hostname() != "127.0.0.1" {
		return errors.New("backend must be on local loopback")
	}
	if err := os.MkdirAll(*dir, 0700); err != nil {
		return err
	}
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()
	node := &tsnet.Server{Dir: *dir, Hostname: *name}
	defer node.Close()
	client, err := node.LocalClient()
	if err != nil {
		return err
	}
	go func() {
		ticker := time.NewTicker(time.Second)
		defer ticker.Stop()
		for {
			state, err := client.StatusWithoutPeers(ctx)
			if err == nil && state.AuthURL != "" {
				_ = writeStatus(*dir, status{Login: state.AuthURL})
			}
			select {
			case <-ticker.C:
			case <-ctx.Done():
				return
			}
		}
	}()
	ready, err := node.Up(ctx)
	if err != nil {
		return err
	}
	listener, err := node.ListenTLS("tcp", ":443")
	if err != nil {
		return err
	}
	defer listener.Close()
	if err := writeStatus(*dir, status{HTTPS: "https://" + strings.TrimSuffix(ready.Self.DNSName, ".")}); err != nil {
		return err
	}
	proxy := &httputil.ReverseProxy{Rewrite: func(req *httputil.ProxyRequest) {
		req.SetURL(target)
		req.SetXForwarded()
	}}
	server := &http.Server{Handler: proxy, ReadHeaderTimeout: 10 * time.Second}
	go func() {
		<-ctx.Done()
		_ = server.Close()
	}()
	err = server.Serve(listener)
	if errors.Is(err, http.ErrServerClosed) {
		return nil
	}
	return err
}

func main() {
	if err := run(); err != nil {
		log.Fatal(err)
	}
}
