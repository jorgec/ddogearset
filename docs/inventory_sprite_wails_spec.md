# Technical Specification
**Sprite-Based Inventory UI Implementation via Wails, Svelte, and Tailwind CSS**
This will be in the same screen as the Vellum Summary view. The user can tab between Vellum Summary and this view

## 1. Architecture Overview
This document outlines the implementation strategy for an inventory user interface utilizing a unified sprite sheet methodology. The application stack consists of a Wails application leveraging a Go backend and a frontend built with Svelte and Tailwind CSS. The objective is to efficiently toggle item slot states (empty vs. equipped) without loading discrete image assets for each state or item.

> **Design Principle:** By treating Svelte components as strict viewports with fixed dimensions, we map negative background coordinates to isolate specific grid segments from the master `harness.jpg` and `harness-disabled.jpg` sprites.

## 2. Asset Management & Configuration

### 2.1 Directory Structure
Place both sprite sheets within the Svelte `assets` directory to ensure the Vite bundler optimizes them correctly during the Wails build process.

```text
frontend/
├── src/
│   ├── assets/
│   │   ├── harness.jpg
│   │   └── harness-disabled.jpg
│   ├── lib/
│   │   └── components/
│   │       ├── InventoryBoard.svelte
│   │       └── InventorySlot.svelte
│   └── App.svelte
```

### 2.2 Tailwind CSS Configuration
To avoid polluting the HTML with lengthy arbitrary background image URLs, define custom utility classes in `tailwind.config.js`. This ensures clean Svelte templates.

```javascript
// tailwind.config.js
export default {
  content: ['./src/**/*.{html,js,svelte,ts}'],
  theme: {
    extend: {
      backgroundImage: {
        'harness-active': "url('/src/assets/harness.jpg')",
        'harness-disabled': "url('/src/assets/harness-disabled.jpg')",
      }
    }
  },
  plugins: []
};
```

### 2.3 Item Placement
From top left, per row, the equipment slots are as follows:
- Goggles, Helmet, Necklace
- Cloak, Armor, Trinket
- Bracers, Belt, Gloves
- Ring 1, Boots, Ring 2
Weapons row:
- Weapon 1, Weapon 2, toggle Vellum Summary View

## 3. Svelte Component Design

### 3.1 InventorySlot.svelte
This atomic component is responsible for rendering a single square. It accepts properties for its coordinate mapping and current equipped state. By utilizing Tailwind's arbitrary value syntax (e.g., `bg-[position:-Xpx_-Ypx]`), we dynamically map the coordinates passed as props.

```svelte
<script>
  // Component Props
  export let itemId = '';
  export let isEquipped = false;
  
  // Sprite Mapping Coordinates (Top-Left of the target square)
  export let coordX = 0;
  export let coordY = 0;
  
  // Assumed fixed dimension of a single slot
  const SLOT_SIZE = 120; 
</script>

<!-- 
  Tailwind Classes Used:
  - w-[120px] h-[120px]: Strict viewport sizing.
  - bg-no-repeat: Prevents sprite tiling.
  - Dynamic background image based on isEquipped boolean.
  - Inline style for background-position to handle dynamic coordinate injection.
-->
<div 
  class="relative inline-block bg-no-repeat transition-colors duration-200 
         w-[{SLOT_SIZE}px] h-[{SLOT_SIZE}px] 
         {isEquipped ? 'bg-harness-active' : 'bg-harness-disabled'}"
  style="background-position: -{coordX}px -{coordY}px;"
  role="button"
  tabindex="0"
  aria-label="Inventory slot for {itemId}"
>
  <!-- Optional: Overlay for hover effects or active states -->
  <div class="absolute inset-0 hover:ring-2 hover:ring-blue-500/50 rounded-sm"></div>
</div>
```

### 3.2 InventoryBoard.svelte
The parent component orchestrates the layout and maps the Wails backend data structure to the individual slots. A configuration object defines the sprite map coordinates.

```svelte
<script>
  import InventorySlot from './InventorySlot.svelte';
  
  // Wails auto-generated bindings
  import { GetInventoryState } from '../../wailsjs/go/main/App.js';
  import { onMount } from 'svelte';

  // Coordinate Map (Derived from image analysis)
  const spriteMap = {
    goggles:  { x: 40,  y: 80  },
    helmet:   { x: 200, y: 80  },
    necklace: { x: 360, y: 80  },
    wings:    { x: 40,  y: 240 },
    armor:    { x: 200, y: 240 },
    // ... complete the map based on harness.jpg
  };

  // State
  let inventory = [];

  onMount(async () => {
    // Fetch state from Go backend on component initialization
    inventory = await GetInventoryState();
  });
</script>

<div class="p-8 bg-slate-900 rounded-xl shadow-2xl inline-flex flex-col gap-4">
  <!-- Example row iteration -->
  <div class="flex gap-4">
    {#each ['goggles', 'helmet', 'necklace'] as slotId}
      <InventorySlot 
        itemId={slotId}
        isEquipped={inventory.includes(slotId)}
        coordX={spriteMap[slotId].x}
        coordY={spriteMap[slotId].y}
      />
    {/each}
  </div>
  
  <div class="flex gap-4">
    {#each ['wings', 'armor'] as slotId}
      <InventorySlot 
        itemId={slotId}
        isEquipped={inventory.includes(slotId)}
        coordX={spriteMap[slotId].x}
        coordY={spriteMap[slotId].y}
      />
    {/each}
  </div>
</div>
```

## 4. Backend Integration (Wails / Go)
The Go backend serves as the source of truth for the inventory state. When an item is equipped or removed, the backend state updates, and Svelte's reactivity handles the DOM update seamlessly.

```go
package main

import "sync"

// App struct
type App struct {
	ctx sync.Mutex
	equippedItems map[string]bool
}

// GetInventoryState returns an array of string IDs representing equipped slots
func (a *App) GetInventoryState() []string {
	a.ctx.Lock()
	defer a.ctx.Unlock()
	
	var equipped []string
	for item, isEquipped := range a.equippedItems {
		if isEquipped {
			equipped = append(equipped, item)
		}
	}
	return equipped
}

// ToggleEquip allows the frontend to trigger an equip/unequip action
func (a *App) ToggleEquip(itemId string) bool {
	a.ctx.Lock()
	defer a.ctx.Unlock()
	
	a.equippedItems[itemId] = !a.equippedItems[itemId]
	return a.equippedItems[itemId]
}
```

## 5. Performance Considerations
* **Memory Footprint:** Using a single sprite sheet rather than 12+ individual image files drastically reduces HTTP requests (in web mode) and memory fragmentation within the Wails webview runtime.
* **Repaint Optimization:** Changing the `background-image` class between `bg-harness-active` and `bg-harness-disabled` is a lightweight CSS operation. Because the layout dimensions and `background-position` remain static, the browser bypasses reflows and only triggers a localized repaint.
