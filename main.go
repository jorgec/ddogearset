package main

import (
	"embed"

	"github.com/wailsapp/wails/v2"
	"github.com/wailsapp/wails/v2/pkg/options"
	"github.com/wailsapp/wails/v2/pkg/options/assetserver"
)

//go:embed all:frontend/dist
var assets embed.FS

func main() {
	// Create an instance of the app structure
	app := NewApp()

	// Create application with options
	err := wails.Run(&options.App{
		Title:  "goGearset",
		Width:  1024,
		Height: 768,
		AssetServer: &assetserver.Options{
			Assets: assets,
		},
		BackgroundColour: &options.RGBA{R: 27, G: 38, B: 54, A: 1},
		// Trove inventory import is drag-and-drop only (there is no file-open
		// button any more), so file drop has to be on for the app to be able
		// to import anything at all. EnableFileDrop is what makes Wails hand
		// the frontend the dropped files' absolute PATHS — the web platform
		// only ever exposes an opaque File — which is what lets Go read the
		// CSV itself instead of shipping it across the IPC bridge.
		//
		// DisableWebViewDrop is required alongside it: EnableFileDrop alone
		// still lets the native webview run its own default drop handling
		// after notifying our JS callback (see performDragOperation in
		// Wails' darwin/WailsWebView.m), which navigates the window to the
		// dropped file and replaces the whole UI with the raw CSV. This
		// suppresses that fallback so only our OnFileDrop handler runs.
		DragAndDrop: &options.DragAndDrop{
			EnableFileDrop:     true,
			DisableWebViewDrop: true,
		},
		OnStartup: app.startup,
		Bind: []interface{}{
			app,
		},
	})

	if err != nil {
		println("Error:", err.Error())
	}
}
