/*
 * Giriş ekranı arka planı: tam ekran slayt + resimden renk paleti. PET Üretim Takip projesinin
 * giriş ekranındaki betiğin (static/js/giris_slayt.js) TypeScript karşılığı;
 * davranış aynı, React sayfası açıkken çalışır ve kapanınca bütün zamanlayıcı ve dinleyicileri bırakır.
 *
 * Her resim yüklenince (ilki hemen, kalanlar tarayıcı boştayken) küçültülüp piksel sayılır:
 * - ZEMİN: en sık görülen renk kovası (stüdyo fonu),
 * - VURGU: zeminden ayrışan, doygun ve sık kova (ürünün rengi),
 * - PARLAKLIK: ortalama; 0,6 üstü "açık kart" (koyu yazı), altı "koyu kart".
 * Bunlardan kart, yazı, düğme, odak halkası ve alt bant renkleri türetilir ve login.module.css'teki
 * kayıtlı özelliklere (@property --lp-*) yazılır; slayt değişince renkler yumuşakça geçer. Her yazı
 * için kontrast denetlenir (düğme yazısı ≥ 4,5:1); yumuşak geçişin ara karesi bir oranı eşiğin altına
 * indirecekse ya da kart açık↔koyu dönerse renkler geçişin ortasında aniden değişir.
 *
 * Geçiş: resimler yatay kayar (yeni sağdan gelir); hareket kısıtında kısa solma, otomatik geçiş durur.
 * Otomatik geçiş duraklatılabilir (WCAG 2.2.2); kullanıcı yazarken son girdiden 4 sn sonrasına kalır.
 */
import { tr } from "../../i18n/tr";
import c from "./login.module.css";

export type Rgb = [number, number, number];

export interface ImageAnalysis {
  bg: Rgb;
  accent: Rgb;
  luminance: number;
}

export interface Palette {
  light: boolean;
  theme: string;
  vars: Record<string, string>;
  buttonTextLight: boolean;
}

const SLIDE_MS = 7000; // bir slaytın ekranda kalma süresi
const TYPING_PAUSE_MS = 4000; // yazarken otomatik geçiş son girdiden bu kadar sonra
const WHITE: Rgb = [255, 255, 255];
const BUTTON_VARS = ["--lp-accent", "--lp-accent-2", "--lp-accent-text"];
const EDGE_BANDS = 10;

const cls = (name: string): string => (c as Record<string, string>)[name] ?? name;

// --- renk yardımcıları (r, g, b: 0–255; h: 0–360; s, l: 0–1) ---------------------------------

export function toHsl(rgb: Rgb): [number, number, number] {
  const r = rgb[0] / 255;
  const g = rgb[1] / 255;
  const b = rgb[2] / 255;
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const l = (max + min) / 2;
  const d = max - min;
  let h = 0;
  let s = 0;
  if (d) {
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    if (max === r) h = (g - b) / d + (g < b ? 6 : 0);
    else if (max === g) h = (b - r) / d + 2;
    else h = (r - g) / d + 4;
    h *= 60;
  }
  return [h, s, l];
}

export function fromHsl(h: number, s: number, l: number): Rgb {
  const channel = (n: number) => {
    const k = (n + h / 30) % 12;
    const a = s * Math.min(l, 1 - l);
    return Math.round(255 * (l - a * Math.max(-1, Math.min(k - 3, 9 - k, 1))));
  };
  return [channel(0), channel(8), channel(4)];
}

function relativeLuminance(rgb: readonly number[]): number {
  const d = rgb.map((v) => {
    const x = v / 255;
    return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * d[0] + 0.7152 * d[1] + 0.0722 * d[2];
}

export function contrast(a: readonly number[], b: readonly number[]): number {
  const x = relativeLuminance(a);
  const y = relativeLuminance(b);
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
}

/** `ratio`: b'nin payı. */
function mix(a: Rgb, b: Rgb, ratio: number): Rgb {
  return [0, 1, 2].map((i) => Math.round(a[i] * (1 - ratio) + b[i] * ratio)) as Rgb;
}

const rgba = (rgb: Rgb, alpha: number) => `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, ${alpha})`;
const hex = (rgb: Rgb) => `#${rgb.map((v) => `0${v.toString(16)}`.slice(-2)).join("")}`;

// --- resim analizi ------------------------------------------------------------------------------

/** Küçültülmüş resmin RGBA piksellerinden zemin, vurgu ve ortalama parlaklık. */
export function analyzePixels(data: ArrayLike<number>): ImageAnalysis {
  const buckets = new Map<number, { n: number; r: number; g: number; b: number }>();
  let brightness = 0;
  const pixels = data.length / 4;
  for (let i = 0; i < data.length; i += 4) {
    const r = data[i];
    const g = data[i + 1];
    const b = data[i + 2];
    const key = ((r >> 4) << 8) | ((g >> 4) << 4) | (b >> 4);
    let bucket = buckets.get(key);
    if (!bucket) {
      bucket = { n: 0, r: 0, g: 0, b: 0 };
      buckets.set(key, bucket);
    }
    bucket.n++;
    bucket.r += r;
    bucket.g += g;
    bucket.b += b;
    brightness += (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
  }
  const list = [...buckets.values()]
    .map((k) => ({
      n: k.n,
      c: [Math.round(k.r / k.n), Math.round(k.g / k.n), Math.round(k.b / k.n)] as Rgb,
    }))
    .sort((x, y) => y.n - x.n);
  const bg = list[0].c;
  // Vurgu: zeminden ayrışan kovalar içinde doygunluk × orta ton × log(sıklık) en yüksek olan.
  let accent: Rgb | null = null;
  let score = -1;
  for (const k of list) {
    if (k.n < 6) continue;
    const distance = Math.abs(k.c[0] - bg[0]) + Math.abs(k.c[1] - bg[1]) + Math.abs(k.c[2] - bg[2]);
    if (distance < 30) continue;
    const [, s, l] = toHsl(k.c);
    const p = s * (1 - Math.abs(l - 0.5) * 1.2) * Math.log(k.n + 1);
    if (p > score) {
      score = p;
      accent = k.c;
    }
  }
  if (!accent) {
    const [h, s, l] = toHsl(bg);
    accent = fromHsl(h, s, Math.max(l - 0.3, 0.2));
  }
  return { bg, accent, luminance: brightness / pixels };
}

function analyze(img: HTMLImageElement): ImageAnalysis | null {
  const canvas = document.createElement("canvas");
  canvas.width = 64;
  canvas.height = 36;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  if (!ctx) return null;
  try {
    ctx.drawImage(img, 0, 0, 64, 36);
    return analyzePixels(ctx.getImageData(0, 0, 64, 36).data);
  } catch {
    return null; // ör. başka kökenli resim: varsayılan palet kalır
  }
}

// --- palet --------------------------------------------------------------------------------------

export function buildPalette(a: ImageAnalysis): Palette {
  const z = a.bg;
  const v = a.accent;
  const light = a.luminance > 0.6;
  const hv = toHsl(v);
  const hz = toHsl(z);
  let text: Rgb;
  let text2: Rgb;
  let card: Rgb;
  let line: string;
  let input: string;
  let inputFocus: string;
  if (light) {
    text = fromHsl(hv[0], Math.min(hv[1], 0.45), 0.16);
    text2 = fromHsl(hv[0], Math.min(hv[1], 0.3), 0.33);
    card = mix(WHITE, z, 0.25);
    line = rgba(text, 0.14);
    input = "rgba(255, 255, 255, 0.6)";
    inputFocus = "rgba(255, 255, 255, 0.85)";
  } else {
    text = fromHsl(hz[0], Math.min(hz[1], 0.25), 0.95);
    text2 = fromHsl(hz[0], Math.min(hz[1], 0.18), 0.8);
    card = fromHsl(hz[0], Math.min(hz[1], 0.22), 0.12);
    line = "rgba(255, 255, 255, 0.16)";
    input = "rgba(255, 255, 255, 0.08)";
    inputFocus = "rgba(255, 255, 255, 0.14)";
  }
  // Koyu cam biraz daha opak: açık resimden koyuya geçerken arkadaki karışım kartı aydınlatmasın.
  const cardAlpha = light ? 0.66 : 0.76;
  const bandAlpha = light ? 0.55 : 0.64;
  // Gözle görülen renkler: yarı saydam kart/bant arkasındaki zeminin üstünde.
  const cardSeen = mix(z, card, cardAlpha);
  const bandSeen = mix(z, card, bandAlpha);
  const focusSeen = mix(cardSeen, WHITE, light ? 0.85 : 0.14);
  // İkincil yazı kartta 5,5:1'e kadar ana yazıya yaklaştırılır (geçişte kart bir an farklı görünür).
  for (let t = 0; t < 10 && contrast(text2, cardSeen) < 5.5; t++) text2 = mix(text2, text, 0.3);

  // Düğme: resmin vurgu rengi. Beyaz yazıyla 4,5:1 için az koyulaştırmak yetiyorsa öyle; vurgu çok
  // açıksa renk korunur, yazı koyu olur. Nötr (gri) resimde doygunluk yükseltilmez.
  const sat = hv[1] < 0.08 ? hv[1] : Math.max(hv[1], 0.35);
  const l0 = hv[2];
  let l = l0;
  let dark = fromHsl(hv[0], sat, l);
  while (contrast(dark, WHITE) < 4.5 && l > 0.1) {
    l -= 0.02;
    dark = fromHsl(hv[0], sat, l);
  }
  let button: Rgb;
  let buttonText: Rgb;
  let button2: Rgb;
  if (l0 - l <= 0.2) {
    button = dark;
    buttonText = WHITE;
    button2 = fromHsl(hv[0], sat, Math.min(l + 0.05, 0.9));
    if (contrast(button2, WHITE) < 4.5) button2 = dark;
  } else {
    button = fromHsl(hv[0], sat, l0);
    buttonText = fromHsl(hv[0], 0.45, 0.13);
    for (let u = 0; u < 10 && contrast(button, buttonText) < 4.5; u++) {
      button = fromHsl(hv[0], sat, Math.max(l0 - 0.03 * (u + 1), 0.3));
    }
    if (contrast(button, buttonText) < 4.5) {
      button = dark;
      buttonText = WHITE;
    }
    button2 = fromHsl(hv[0], sat, Math.max(toHsl(button)[2] - 0.05, 0.1));
  }
  // Düğme kartta kaybolmasın: kartla 2:1 ayrışmıyorsa tonu korunarak koyu kartta açılır, açık kartta
  // koyulaşır; yazı rengi ikisinden hangisi daha okunaklıysa o olur (≥ 4,5:1).
  const darkText = fromHsl(hv[0], 0.45, 0.13);
  const pickText = (rgb: Rgb) =>
    contrast(rgb, WHITE) >= contrast(rgb, darkText) ? WHITE : darkText;
  if (contrast(button, cardSeen) < 2) {
    const hd = toHsl(button);
    const dir = light ? -1 : 1;
    const ds = hd[1] < 0.08 ? hd[1] : Math.max(hd[1], 0.35);
    for (let w = 0; w < 45; w++) {
      const candidate = fromHsl(hd[0], ds, hd[2]);
      if (contrast(candidate, cardSeen) >= 2 && contrast(candidate, pickText(candidate)) >= 4.5)
        break;
      hd[2] = Math.min(0.92, Math.max(0.06, hd[2] + dir * 0.02));
    }
    button = fromHsl(hd[0], ds, hd[2]);
    buttonText = pickText(button);
    button2 = fromHsl(hd[0], ds, Math.min(0.92, Math.max(0.06, hd[2] + dir * 0.04)));
    if (contrast(button2, buttonText) < 4.5) button2 = button;
  }
  const brand = contrast(button, z) >= 3 ? button : text;
  // Odak çerçevesi (WCAG 1.4.11 / 2.4.7): kart, bant ve odaklı alana karşı ≥ 3:1; olmuyorsa ana yazı.
  const focusLine = [cardSeen, bandSeen, focusSeen].every((bgc) => contrast(button, bgc) >= 3)
    ? button
    : text;
  return {
    light,
    theme: hex(z),
    vars: {
      "--lp-bg": hex(z),
      "--lp-text": hex(text),
      "--lp-text-2": hex(text2),
      "--lp-accent": hex(button),
      "--lp-accent-2": hex(button2),
      "--lp-accent-text": hex(buttonText),
      "--lp-brand": hex(brand),
      "--lp-card": rgba(card, cardAlpha),
      "--lp-band": rgba(card, bandAlpha),
      "--lp-line": line,
      "--lp-input": input,
      "--lp-input-focus": inputFocus,
      "--lp-focus": rgba(focusLine, 0.35),
      "--lp-focus-line": hex(focusLine),
    },
    buttonTextLight: relativeLuminance(buttonText) > 0.5,
  };
}

// --- geçiş yolunun denetimi ---------------------------------------------------------------------
// Ekranda iki palet arasındaki ara renkler görünür; aynı kipteki iki palette bile yumuşak geçişin
// ortasında bir oran iki uçtakinin de altına inebilir. Tarayıcının hesabı burada tekrarlanır (kayıtlı
// <color>: önceden çarpılmış alfa ile sRGB ara değeri) ve 21 noktada sınanır.

interface Rgba {
  c: number[];
  a: number;
}

function parseColor(s: string): Rgba {
  if (s.startsWith("#")) return { c: [1, 3, 5].map((k) => parseInt(s.slice(k, k + 2), 16)), a: 1 };
  const v = s
    .slice(s.indexOf("(") + 1, s.indexOf(")"))
    .split(",")
    .map(Number);
  return { c: [v[0], v[1], v[2]], a: v.length > 3 ? v[3] : 1 };
}

function between(x: Rgba, y: Rgba, t: number): Rgba {
  const a = x.a * (1 - t) + y.a * t;
  if (!a) return { c: [0, 0, 0], a: 0 };
  return { c: [0, 1, 2].map((k) => (x.c[k] * x.a * (1 - t) + y.c[k] * y.a * t) / a), a };
}

const over = (base: number[], top: Rgba) =>
  [0, 1, 2].map((k) => base[k] * (1 - top.a) + top.c[k] * top.a);

/** Denetlenen oranlar ve eşikleri (buildPalette'teki güvencelerle aynı). */
function ratios(d: Record<string, Rgba>): [number, number][] {
  const z = d["--lp-bg"].c;
  const cardSeen = over(z, d["--lp-card"]);
  const bandSeen = over(z, d["--lp-band"]);
  const inputSeen = over(cardSeen, d["--lp-input-focus"]);
  const m = d["--lp-text"].c;
  const m2 = d["--lp-text-2"].c;
  const o = d["--lp-focus-line"].c;
  const v = d["--lp-accent"].c;
  return [
    [contrast(m, cardSeen), 4.5],
    [contrast(m2, cardSeen), 4.5],
    [contrast(m2, bandSeen), 3],
    [contrast(o, cardSeen), 3],
    [contrast(o, bandSeen), 3],
    [contrast(o, inputSeen), 3],
    [contrast(v, cardSeen), 2],
    [contrast(v, d["--lp-accent-text"].c), 4.5],
  ];
}

/** `instant`: ani değişen özellikler (yolda hep yeni değerinde); kalanı yumuşak ilerler. */
function pathHolds(from: Palette, to: Palette, instant: string[]): boolean {
  const names = Object.keys(to.vars);
  const x: Record<string, Rgba> = {};
  const y: Record<string, Rgba> = {};
  for (const k of names) {
    x[k] = parseColor(from.vars[k]);
    y[k] = parseColor(to.vars[k]);
  }
  const endA = ratios(x);
  const endB = ratios(y);
  for (let s = 0; s <= 20; s++) {
    const d: Record<string, Rgba> = {};
    for (const k of names) d[k] = instant.includes(k) ? y[k] : between(x[k], y[k], s / 20);
    const r = ratios(d);
    for (let j = 0; j < r.length; j++) {
      if (r[j][0] < Math.min(r[j][1], endA[j][0], endB[j][0]) - 0.005) return false;
    }
  }
  return true;
}

/** Bir paletten ötekine geçişin biçimi: bütün palet ani, düğme üçlüsü ani ya da yumuşak. */
export function transitionMode(from: Palette, to: Palette): "card" | "button" | "smooth" {
  const buttonFlips = from.buttonTextLight !== to.buttonTextLight;
  if (from.light !== to.light || !pathHolds(from, to, buttonFlips ? BUTTON_VARS : [])) {
    return "card";
  }
  return buttonFlips ? "button" : "smooth";
}

// --- kenar dolgusu ------------------------------------------------------------------------------
// Resim ekranı kaplamadığında kalan yer, resmin sol ve sağ KENAR renklerinden yapılmış dikey
// geçişlerle dolar (10 bant); resmin maskeli kenarı bu dolguya karışır, ek yeri görünmez.

function edgeFill(img: HTMLImageElement): { left: string; right: string } | null {
  const w = 60;
  const h = Math.max(EDGE_BANDS, Math.round((w * img.naturalHeight) / img.naturalWidth));
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  if (!ctx) return null;
  let v: Uint8ClampedArray;
  try {
    ctx.drawImage(img, 0, 0, w, h);
    v = ctx.getImageData(0, 0, w, h).data;
  } catch {
    return null;
  }
  const average = (x0: number, x1: number, y0: number, y1: number): Rgb => {
    let r = 0;
    let g = 0;
    let b = 0;
    let n = 0;
    for (let y = y0; y < y1; y++) {
      for (let x = x0; x < x1; x++) {
        const k = (y * w + x) * 4;
        r += v[k];
        g += v[k + 1];
        b += v[k + 2];
        n++;
      }
    }
    return [Math.round(r / n), Math.round(g / n), Math.round(b / n)];
  };
  const gradient = (colors: Rgb[]) =>
    `linear-gradient(to bottom, ${colors
      .map((col, i) => `${hex(col)} ${Math.round((i * 100) / (colors.length - 1))}%`)
      .join(", ")})`;
  const left: Rgb[] = [];
  const right: Rgb[] = [];
  for (let i = 0; i < EDGE_BANDS; i++) {
    const y0 = Math.floor((i * h) / EDGE_BANDS);
    const y1 = Math.max(y0 + 1, Math.floor(((i + 1) * h) / EDGE_BANDS));
    left.push(average(0, 2, y0, y1));
    right.push(average(w - 2, w, y0, y1));
  }
  return { left: gradient(left), right: gradient(right) };
}

// --- slayt --------------------------------------------------------------------------------------

/**
 * Kökteki slaytları ve denetimleri çalıştırır; dönen işlev her şeyi durdurur. Resim yoksa ya da
 * öğeler bulunamazsa hiçbir şey yapmaz (ilk resim durur, renkler CSS varsayılanıdır).
 */
export function startSlideshow(root: HTMLElement): () => void {
  const stage = root.querySelector<HTMLElement>(`.${cls("slides")}`);
  const slides = stage ? [...stage.querySelectorAll<HTMLElement>(`.${cls("slide")}`)] : [];
  const images = slides.map((s) => s.querySelector("img"));
  if (!stage || !slides.length || images.some((g) => !g)) return () => {};
  const imgs = images as HTMLImageElement[];

  let stopped = false;
  const timers = new Set<number>();
  const later = (fn: () => void, ms: number): number => {
    const id = window.setTimeout(() => {
      timers.delete(id);
      if (!stopped) fn();
    }, ms);
    timers.add(id);
    return id;
  };
  const cancel = (id: number | null | undefined) => {
    if (id == null) return;
    window.clearTimeout(id);
    timers.delete(id);
  };
  const cleanups: (() => void)[] = [];
  const listen = <T extends EventTarget>(
    target: T,
    type: string,
    fn: EventListenerOrEventListenerObject,
    opts?: AddEventListenerOptions,
  ) => {
    target.addEventListener(type, fn, opts);
    cleanups.push(() => target.removeEventListener(type, fn, opts));
  };

  const reduceQuery = window.matchMedia
    ? window.matchMedia("(prefers-reduced-motion: reduce)")
    : null;
  let reduced = !!reduceQuery?.matches;
  const canSlide = () => !reduced && !!window.CSS?.supports?.("translate", "0");
  let sliding = canSlide();
  let transitionMs = sliding ? 900 : reduced ? 300 : 1400;
  const palettes: (Palette | null | undefined)[] = [];
  let current = 0;
  let paused = reduced;
  let cycleTimer: number | null = null;
  let decodeTimer: number | null = null;

  // Sahne alt bandın üstünde biter; bandın gerçek yüksekliği --lp-footer-h olur. Telefonda (≤ 600 px)
  // sahne kartın altındaki bantla sınırlıdır (--lp-mobile-stage-top).
  const footer = root.querySelector<HTMLElement>(`.${cls("footer-band")}`);
  const card = root.querySelector<HTMLElement>(`.${cls("card")}`);
  const phone = window.matchMedia ? window.matchMedia("(max-width: 600px)") : null;
  const measure = () => {
    if (footer) {
      root.style.setProperty(
        "--lp-footer-h",
        `${Math.ceil(footer.getBoundingClientRect().height)}px`,
      );
    }
    if (!card || !phone?.matches) {
      root.style.removeProperty("--lp-mobile-stage-top");
      return;
    }
    const bottomBand = footer ? footer.getBoundingClientRect().height : 80;
    let top = Math.round(card.getBoundingClientRect().bottom + root.scrollTop + 10);
    top = Math.min(top, Math.round(window.innerHeight - bottomBand - 120));
    root.style.setProperty("--lp-mobile-stage-top", `${Math.max(0, top)}px`);
  };
  measure();
  if (window.ResizeObserver) {
    const observer = new ResizeObserver(measure);
    if (footer) observer.observe(footer);
    if (card) observer.observe(card); // hata iletisi çıkınca kart uzar
    cleanups.push(() => observer.disconnect());
  }
  listen(window, "resize", measure);

  // --- paletin uygulanması -----------------------------------------------------------------
  let applied: Palette | null = null;
  let instantTimer: number | null = null;
  const frames: number[] = [];

  const write = (p: Palette) => {
    applied = p;
    for (const [name, value] of Object.entries(p.vars)) root.style.setProperty(name, value);
    root.setAttribute("data-card", p.light ? "light" : "dark");
  };
  // İki kare sonra geçişler geri gelir; değerler yerinde olduğu için yeniden oynamaz.
  const endInstant = () => {
    frames.push(
      requestAnimationFrame(() => {
        frames.push(
          requestAnimationFrame(() => {
            root.classList.remove(cls("instant-card"), cls("instant-button"));
          }),
        );
      }),
    );
  };
  const apply = (p: Palette) => {
    const previous = applied;
    cancel(instantTimer);
    // İlk palet CSS varsayılanlarının düzeltmesidir: geçişsiz yazılır.
    if (!previous) {
      root.classList.add(cls("instant-card"));
      write(p);
      endInstant();
      return;
    }
    const mode = transitionMode(previous, p);
    if (mode === "smooth") {
      write(p);
      return;
    }
    instantTimer = later(
      () => {
        root.classList.add(cls(mode === "card" ? "instant-card" : "instant-button"));
        write(p);
        endInstant();
      },
      reduced ? 0 : transitionMs / 2,
    );
  };

  const ready = (img: HTMLImageElement) => img.complete && img.naturalWidth > 0;

  const filled = slides.map(() => false);
  const fillEdges = (i: number) => {
    if (filled[i] || !ready(imgs[i])) return;
    filled[i] = true; // çözülemezse de yeniden denenmez
    const d = edgeFill(imgs[i]);
    if (!d) return;
    slides[i].style.setProperty("--lp-fill-left", d.left);
    slides[i].style.setProperty("--lp-fill-right", d.right);
  };
  // Etkin olmayan resimlerin analizi ve dolgusu boşta çalışır: açılışta yazarken tuşlar gecikmesin.
  const whenIdle = (fn: () => void) => {
    if (window.requestIdleCallback) {
      const id = window.requestIdleCallback(() => !stopped && fn(), { timeout: 2000 });
      cleanups.push(() => window.cancelIdleCallback?.(id));
    } else {
      later(fn, 250);
    }
  };
  const preparePalette = (i: number): Palette | null | undefined => {
    if (palettes[i] !== undefined) return palettes[i];
    if (!ready(imgs[i])) return undefined;
    const a = analyze(imgs[i]);
    palettes[i] = a ? buildPalette(a) : null;
    return palettes[i];
  };

  // --- slayt geçişi --------------------------------------------------------------------------
  const dots: HTMLButtonElement[] = [];
  const dead = slides.map(() => false); // inmeyen ya da çözülemeyen resim
  const leavingTimers: (number | null)[] = slides.map(() => null);
  const controls = root.querySelector<HTMLElement>(`.${cls("slide-controls")}`);
  const toggle = root.querySelector<HTMLButtonElement>(`.${cls("slide-toggle")}`);
  const dotsBox = root.querySelector<HTMLElement>(`.${cls("slide-dots")}`);
  const aliveCount = () => dead.filter((x) => !x).length;

  const updateDots = () => {
    dots.forEach((d, i) => {
      if (i === current) d.setAttribute("aria-current", "true");
      else d.removeAttribute("aria-current");
      d.hidden = dead[i];
    });
    // Geçecek en az iki resim kalmadıysa denetim anlamsız: gizlenir, döngü durur.
    if (controls) controls.hidden = aliveCount() < 2 || dots.length < 2;
  };

  const xOf = (s: HTMLElement) =>
    s.getBoundingClientRect().left - stage.getBoundingClientRect().left;
  // Çıkan katman geçiş bitince temizlenir; satır içi konumu da silinir.
  const finishLeaving = (no: number, s: HTMLElement) => {
    cancel(leavingTimers[no]);
    leavingTimers[no] = later(() => {
      s.classList.remove(cls("is-leaving"));
      s.style.removeProperty("translate");
    }, transitionMs + 120);
  };

  /** dir: 1 = ileri (yeni sağdan gelir), -1 = geri; verilmezse noktanın yerinden. */
  const show = (i: number, dir?: number) => {
    if (i === current || dead[i]) return;
    const old = slides[current];
    const next = slides[i];
    const oldNo = current;
    let forward = (dir || (i > current ? 1 : -1)) > 0;
    fillEdges(i);
    cancel(leavingTimers[i]);
    let interrupted = false;
    let width = 0;
    const visible: HTMLElement[] = [];
    const positions: number[] = [];
    let nextX: number | null = null;
    if (sliding) {
      width = stage.clientWidth;
      const onScreen = (x: number) => x > 1 - width && x < width - 1;
      visible.push(old);
      positions.push(xOf(old));
      for (const s of slides) {
        if (s === next || s === old || !s.classList.contains(cls("is-leaving"))) continue;
        const x = xOf(s);
        if (onScreen(x)) {
          visible.push(s);
          positions.push(x);
        }
      }
      if (next.classList.contains(cls("is-leaving"))) {
        const y = xOf(next);
        if (onScreen(y) && positions.every((x) => Math.abs(x - y) >= width - 1)) nextX = y;
      }
      const moving = old.getAnimations
        ? old.getAnimations().length > 0
        : Math.abs(positions[0]) > 1;
      interrupted = visible.length > 1 || nextX !== null || moving;
    }
    if (interrupted) {
      // Kesilen kayma: görünen katmanlar tek şerit gibi aynı mesafeyi birlikte kayar; gelen katman
      // görünen bir katmanın yerine hiç konmaz.
      const startX =
        nextX !== null
          ? nextX
          : forward
            ? Math.max(...positions) + width
            : Math.min(...positions) - width;
      const shift = -startX;
      forward = shift < 0;
      visible.forEach((s, k) => {
        s.classList.add(cls("is-preparing"));
        s.style.translate = `${positions[k]}px 0`;
      });
      next.classList.add(cls("is-preparing"));
      next.style.translate = `${startX}px 0`;
      void stage.offsetWidth;
      stage.classList.add(cls("is-interrupted"));
      visible.forEach((s, k) => {
        s.classList.remove(cls("is-preparing"));
        s.style.translate = `${positions[k] + shift}px 0`;
        if (s !== old) finishLeaving(slides.indexOf(s), s);
      });
      next.classList.remove(cls("is-preparing"));
      next.style.removeProperty("translate");
    } else {
      stage.classList.remove(cls("is-interrupted"));
      next.style.removeProperty("translate");
      if (sliding) {
        next.classList.remove(cls("is-right"), cls("is-left"));
        next.classList.add(cls("is-preparing"), cls(forward ? "is-right" : "is-left"));
        void next.offsetWidth;
        next.classList.remove(cls("is-preparing"));
      }
    }
    next.classList.remove(cls("is-leaving"), cls("is-right"), cls("is-left"));
    old.classList.remove(cls("is-active"), cls("is-right"), cls("is-left"));
    old.classList.add(cls("is-leaving"));
    if (sliding) old.classList.add(cls(forward ? "is-left" : "is-right"));
    finishLeaving(oldNo, old);
    next.classList.add(cls("is-active"));
    current = i;
    const p = preparePalette(i);
    if (p) apply(p);
    updateDots();
  };

  /** Sıradaki gösterilebilir resim: ölüler atlanır, inmemiş olan beklenmez. */
  const nextReady = () => {
    for (let step = 1; step < slides.length; step++) {
      const j = (current + step) % slides.length;
      if (!dead[j] && ready(imgs[j])) return j;
    }
    return -1;
  };

  // Kullanıcı yazarken arka plan ilerlemez (kart açık↔koyu dönerse imlecin altındaki yazı ve zemin
  // yer değiştirir); sıradaki geçiş son girdiden 4 sn sonrasına kalır. Duraklatma değildir.
  let lastTyping = -Infinity;
  const form = root.querySelector("form");
  if (form) listen(form, "input", () => (lastTyping = performance.now()));

  // Sıradaki resim kaymadan 1 sn önce çözülür (büyük WebP ilk karelerde çözülmesin).
  const predecode = (j: number) => {
    const g = j >= 0 ? imgs[j] : null;
    if (g?.decode && ready(g)) g.decode().catch(() => {});
  };

  const advance = () => {
    const wait = lastTyping + TYPING_PAUSE_MS - performance.now();
    if (wait > 0) {
      cycleTimer = later(advance, wait);
      return;
    }
    const j = nextReady();
    if (j >= 0) show(j, 1);
    schedule();
  };

  const schedule = () => {
    cancel(cycleTimer);
    cancel(decodeTimer);
    root.setAttribute("data-slides", paused ? "paused" : "playing");
    if (paused || aliveCount() < 2 || document.hidden) return;
    decodeTimer = later(() => predecode(nextReady()), SLIDE_MS - 1000);
    cycleTimer = later(advance, SLIDE_MS);
  };

  // Resim yüklenince paleti hazırlanır: etkin resminki hemen, kalanlar boştayken. İnmeyen resim çıkar.
  imgs.forEach((img, i) => {
    const died = () => {
      dead[i] = true;
      if (i === current) {
        const j = nextReady();
        if (j >= 0) show(j);
      }
      updateDots();
      schedule();
    };
    const loaded = () => {
      if (stopped) return;
      if (!ready(img)) {
        died(); // complete ama çözülemedi (naturalWidth = 0)
        return;
      }
      if (i === current) {
        fillEdges(i);
        const p = preparePalette(i);
        if (p) apply(p);
      } else {
        whenIdle(() => {
          fillEdges(i);
          preparePalette(i);
        });
      }
    };
    if (img.complete) loaded();
    else {
      listen(img, "load", loaded, { once: true });
      listen(img, "error", () => !stopped && died(), { once: true });
    }
  });

  // --- denetimler (birden çok resim varsa) ----------------------------------------------------
  // aria-pressed durumu söyler (basılı = duraklatıldı); etiket sabit, yalnızca ipucu değişir.
  const pausedState = () => {
    if (!toggle) return;
    toggle.setAttribute("aria-pressed", paused ? "true" : "false");
    toggle.title = paused ? tr.auth.slideResume : tr.auth.slidePause;
  };
  if (controls && dotsBox && slides.length > 1) {
    slides.forEach((_, i) => {
      const d = document.createElement("button");
      d.type = "button";
      d.className = cls("slide-dot");
      d.setAttribute("aria-label", tr.auth.slideLabel(i + 1));
      d.title = tr.auth.slideLabel(i + 1);
      listen(d, "click", () => {
        if (!dead[i] && ready(imgs[i])) show(i);
        schedule();
      });
      // Üzerine gelince ya da odaklanınca o resim önceden çözülür.
      listen(d, "pointerenter", () => predecode(i));
      listen(d, "focus", () => predecode(i));
      dotsBox.appendChild(d);
      dots.push(d);
    });
    cleanups.push(() => dots.forEach((d) => d.remove()));
    if (toggle) {
      listen(toggle, "click", () => {
        paused = !paused;
        pausedState();
        schedule();
      });
    }
    pausedState();
    updateDots();
  }

  root.classList.add(cls("is-scripted")); // yakınlaşma yalnızca duraklatılabilirken
  listen(document, "visibilitychange", schedule);
  // Hareket kısıtı sayfa açıkken değişirse kayma/süre CSS'le aynı kalsın; kısıt açılınca otomatik
  // geçiş durur, kapanınca kendiliğinden sürmez.
  const reducedChanged = () => {
    reduced = !!reduceQuery?.matches;
    sliding = canSlide();
    transitionMs = sliding ? 900 : reduced ? 300 : 1400;
    if (!sliding) {
      stage.classList.remove(cls("is-interrupted"));
      slides.forEach((s) => s.style.removeProperty("translate"));
    }
    if (reduced) {
      paused = true;
      pausedState();
    }
    schedule();
  };
  if (reduceQuery?.addEventListener) listen(reduceQuery, "change", reducedChanged);
  schedule();

  return () => {
    stopped = true;
    timers.forEach((id) => window.clearTimeout(id));
    timers.clear();
    frames.forEach((id) => cancelAnimationFrame(id));
    cleanups.forEach((fn) => fn());
  };
}
