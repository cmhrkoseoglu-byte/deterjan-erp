import { describe, expect, it } from "vitest";
import {
  analyzePixels,
  buildPalette,
  contrast,
  transitionMode,
  type ImageAnalysis,
  type Rgb,
} from "./slideshow";

const rgb = (hex: string): Rgb => [1, 3, 5].map((k) => parseInt(hex.slice(k, k + 2), 16)) as Rgb;

/** Yarı saydam kartın zemin üstünde görünen rengi (paletteki rgba + zemin). */
function seen(bg: string, layer: string): Rgb {
  const [r, g, b, a] = layer
    .slice(layer.indexOf("(") + 1, -1)
    .split(",")
    .map(Number);
  const z = rgb(bg);
  return [r, g, b].map((v, i) => Math.round(z[i] * (1 - a) + v * a)) as Rgb;
}

function pixels(parts: [Rgb, number][]): number[] {
  return parts.flatMap(([c, n]) => Array.from({ length: n }, () => [...c, 255]).flat());
}

// PET ERP'deki 01 (açık mavi şişeler) ve koyu fonlu bir ürün fotoğrafına benzer analizler.
const LIGHT: ImageAnalysis = { bg: [205, 214, 226], accent: [120, 150, 210], luminance: 0.78 };
const DARK: ImageAnalysis = { bg: [20, 22, 26], accent: [40, 140, 90], luminance: 0.12 };
const PEACH: ImageAnalysis = { bg: [236, 232, 226], accent: [240, 196, 140], luminance: 0.86 };

describe("resim analizi", () => {
  it("zemin en sık renk, vurgu zeminden ayrışan doygun renk", () => {
    const data = pixels([
      [[200, 205, 210], 1800],
      [[30, 90, 200], 400],
      [[190, 196, 201], 104],
    ]);
    const a = analyzePixels(data);
    expect(a.bg).toEqual([200, 205, 210]);
    expect(a.accent).toEqual([30, 90, 200]);
    expect(a.luminance).toBeGreaterThan(0.6);
  });
});

describe("palet", () => {
  it.each([
    ["açık", LIGHT],
    ["koyu", DARK],
    ["açık vurgulu", PEACH],
  ])("%s fotoğrafta yazılar ve düğme okunur", (_, analysis) => {
    const p = buildPalette(analysis);
    const v = p.vars;
    const card = seen(v["--lp-bg"], v["--lp-card"]);
    expect(contrast(rgb(v["--lp-text"]), card)).toBeGreaterThanOrEqual(4.5);
    expect(contrast(rgb(v["--lp-text-2"]), card)).toBeGreaterThanOrEqual(4.5);
    expect(contrast(rgb(v["--lp-accent"]), rgb(v["--lp-accent-text"]))).toBeGreaterThanOrEqual(4.5);
    expect(contrast(rgb(v["--lp-accent"]), card)).toBeGreaterThanOrEqual(2);
    expect(contrast(rgb(v["--lp-focus-line"]), card)).toBeGreaterThanOrEqual(3);
    expect(contrast(rgb(v["--lp-brand"]), rgb(v["--lp-bg"]))).toBeGreaterThanOrEqual(3);
  });

  it("logo açık zeminde kendi laciverti, koyu zeminde beyaz", () => {
    expect(buildPalette(LIGHT).vars["--lp-brand"]).toBe("#02225c");
    expect(buildPalette(PEACH).vars["--lp-brand"]).toBe("#02225c");
    expect(buildPalette(DARK).vars["--lp-brand"]).toBe("#ffffff");
  });

  it("parlaklığa göre açık ya da koyu kart", () => {
    expect(buildPalette(LIGHT).light).toBe(true);
    expect(buildPalette(DARK).light).toBe(false);
  });

  it("aynı kipte yumuşak, açık↔koyu dönüşte ani geçiş", () => {
    expect(transitionMode(buildPalette(LIGHT), buildPalette(LIGHT))).toBe("smooth");
    expect(transitionMode(buildPalette(LIGHT), buildPalette(DARK))).toBe("card");
  });
});
