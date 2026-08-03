import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Helper to convert HEX to RGB
function hexToRgb(hex) {
  hex = hex.replace(/^#/, '');
  if (hex.length === 3) {
    hex = hex.split('').map(c => c + c).join('');
  }
  const num = parseInt(hex, 16);
  return {
    r: (num >> 16) & 255,
    g: (num >> 8) & 255,
    b: num & 255
  };
}

// Relative luminance calculation for WCAG
function getLuminance({ r, g, b }) {
  const [rs, gs, bs] = [r / 255, g / 255, b / 255].map(c => {
    return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * rs + 0.7152 * gs + 0.0722 * bs;
}

// Contrast ratio calculation
function getContrastRatio(hex1, hex2) {
  const l1 = getLuminance(hexToRgb(hex1));
  const l2 = getLuminance(hexToRgb(hex2));
  const brightest = Math.max(l1, l2);
  const darkest = Math.min(l1, l2);
  return (brightest + 0.05) / (darkest + 0.05);
}

// The Tailwind config colors (manually extracted here for verification, 
// in a full pipeline this would require importing the config)
const colors = {
  background: "#f4f5f7",
  foreground: "#0d131c",
  primary: { bg: "#00798c", fg: "#f4f5f7" },
  secondary: { bg: "#d9dde1", fg: "#0d131c" },
  destructive: { bg: "#d1495b", fg: "#c59da1" },
  muted: { bg: "#d9dde1", fg: "#1c2430" },
  accent: { bg: "#edae49", fg: "#0d131c" },
  card: { bg: "#ffffff", fg: "#0d131c" }
};

let fails = 0;

console.log("🎨 Running WCAG Contrast Ratio Checker...\n");

function checkPair(name, bg, fg, minimum = 4.5) {
  const ratio = getContrastRatio(bg, fg).toFixed(2);
  if (ratio >= minimum) {
    console.log(`✅ [${name}] bg: ${bg}, fg: ${fg} -> Ratio: ${ratio}:1 (Passes WCAG AA)`);
  } else {
    console.log(`❌ [${name}] bg: ${bg}, fg: ${fg} -> Ratio: ${ratio}:1 (FAILS WCAG AA minimum of ${minimum}:1)`);
    fails++;
  }
}

// Global Text on Global Background
checkPair("Global Body", colors.background, colors.foreground);
// Primary Button
checkPair("Primary Button", colors.primary.bg, colors.primary.fg);
// Secondary Button
checkPair("Secondary Button", colors.secondary.bg, colors.secondary.fg);
// Destructive Button
checkPair("Destructive Button", colors.destructive.bg, colors.destructive.fg);
// Muted Text on Global Background
checkPair("Muted Text on Bg", colors.background, colors.muted.fg);
// Accent Element
checkPair("Accent Element", colors.accent.bg, colors.accent.fg);
// Card Text
checkPair("Card Text", colors.card.bg, colors.card.fg);

console.log("\n");
if (fails > 0) {
  console.error(`🚨 ${fails} color combinations failed WCAG accessibility standards.`);
  process.exit(1);
} else {
  console.log("🎉 All configured color pairs pass WCAG accessibility standards!");
  process.exit(0);
}
