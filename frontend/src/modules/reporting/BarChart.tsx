import { Paper, Text } from "@mantine/core";
import { useElementSize } from "@mantine/hooks";
import { useState } from "react";
import { formatNumber } from "../../i18n/format";

export interface BarPoint {
  /** Eksendeki kısa etiket (ör. 24.10). */
  label: string;
  /** İpucunun başlığı (ör. 24.10.2026 Cuma). */
  title: string;
  value: number;
}

const HEIGHT = 200;
const TOP = 12;
const BOTTOM = 26;
const RADIUS = 4;
const TIP_WIDTH = 150;
const TIP_HEIGHT = 46;
const TIP_GAP = 6;
const BAR = "var(--mantine-primary-color-filled)";
const BAR_ACTIVE = "var(--mantine-primary-color-filled-hover)";
const GRID = "var(--mantine-color-default-border)";
const INK = "var(--mantine-color-dimmed)";

/** Sıfırdan başlayan eksen: 1-2-2,5-5 × 10ⁿ adımlarla en çok beş aralık; adım en az 1. */
function niceScale(max: number): { top: number; step: number } {
  if (!(max > 0)) return { top: 1, step: 1 };
  const rough = max / 4;
  const magnitude = 10 ** Math.floor(Math.log10(rough));
  const step = Math.max(
    1,
    [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((s) => s >= rough)!,
  );
  return { top: Math.ceil(max / step) * step, step };
}

/** Yalnızca üst köşeleri yuvarlak çubuk; taban eksene düz oturur. */
function barPath(x: number, y: number, width: number, height: number): string {
  const r = Math.min(RADIUS, width / 2, height);
  return (
    `M${x},${y + height}V${y + r}A${r},${r} 0 0 1 ${x + r},${y}` +
    `H${x + width - r}A${r},${r} 0 0 1 ${x + width},${y + r}V${y + height}Z`
  );
}

/**
 * Tek serili sütun grafik (tek renk). Üzerine gelince (dokununca) günün değeri görünür;
 * erişilebilir eşi çağıranın gösterdiği tablodur.
 */
export function BarChart({
  points,
  unit,
  summary,
}: {
  points: BarPoint[];
  unit: string;
  /** Ekran okuyucu için tek cümlelik özet. */
  summary: string;
}) {
  const { ref, width } = useElementSize();
  const [active, setActive] = useState<number | null>(null);
  const { top, step } = niceScale(Math.max(0, ...points.map((p) => p.value)));
  const ticks: number[] = [];
  for (let value = 0; value <= top; value += step) ticks.push(value);
  const tickLabels = ticks.map((value) => formatNumber(value, 0));
  const left = 10 + Math.max(...tickLabels.map((label) => label.length)) * 7;
  const plotHeight = HEIGHT - TOP - BOTTOM;
  const band = points.length ? Math.max(0, width - left - 4) / points.length : 0;
  const barWidth = Math.max(4, Math.min(24, band * 0.6));
  // Dar ekranda her gün etiketlenmez; bugünün (son gün) etiketi her zaman görünür.
  const every = band >= 36 ? 1 : band >= 18 ? 2 : 3;
  const last = points.length - 1;
  const y = (value: number) => TOP + plotHeight - (value / top) * plotHeight;
  const point = active === null ? null : points[active];
  const center = active === null ? 0 : left + active * band + band / 2;
  // İpucu çubuğun yanında, tepesi hizasında durur; çubuğu örtmez. Sağda yer yoksa solda.
  const tipTop = point ? Math.min(y(point.value), TOP + plotHeight - TIP_HEIGHT) : 0;
  const tipRight = center + barWidth / 2 + TIP_GAP + TIP_WIDTH <= width;

  return (
    <div
      ref={ref}
      style={{ position: "relative", height: HEIGHT }}
      onMouseLeave={() => setActive(null)}
    >
      {width > 0 && (
        <svg width={width} height={HEIGHT} role="img" aria-label={summary}>
          {ticks.map((value, i) => (
            <g key={value}>
              <line x1={left} x2={width - 4} y1={y(value)} y2={y(value)} stroke={GRID} />
              <text x={left - 6} y={y(value)} dy="0.32em" textAnchor="end" fontSize={11} fill={INK}>
                {tickLabels[i]}
              </text>
            </g>
          ))}
          {active !== null && (
            <rect
              x={left + active * band}
              y={TOP}
              width={band}
              height={plotHeight}
              fill="var(--mantine-color-default-hover)"
            />
          )}
          {points.map((p, i) => {
            const height = (p.value / top) * plotHeight;
            if (height <= 0) return null;
            return (
              <path
                key={p.label}
                d={barPath(
                  left + i * band + (band - barWidth) / 2,
                  TOP + plotHeight - height,
                  barWidth,
                  height,
                )}
                fill={i === active ? BAR_ACTIVE : BAR}
              />
            );
          })}
          {points.map((p, i) =>
            (last - i) % every === 0 ? (
              <text
                key={p.label}
                x={left + i * band + band / 2}
                y={HEIGHT - 8}
                textAnchor="middle"
                fontSize={11}
                fontWeight={i === last ? 700 : 400}
                fill={INK}
              >
                {p.label}
              </text>
            ) : null,
          )}
          {/* Dokunma / fare hedefi sütundan geniştir: günün bütün şeridi. */}
          {points.map((p, i) => (
            <rect
              key={p.label}
              x={left + i * band}
              y={TOP}
              width={band}
              height={HEIGHT - TOP}
              fill="transparent"
              onMouseEnter={() => setActive(i)}
              onClick={() => setActive(i)}
            />
          ))}
        </svg>
      )}
      {point && (
        <Paper
          shadow="sm"
          withBorder
          px={8}
          py={4}
          style={{
            position: "absolute",
            left: tipRight ? center + barWidth / 2 + TIP_GAP : center - barWidth / 2 - TIP_GAP,
            top: tipTop,
            transform: tipRight ? undefined : "translateX(-100%)",
            pointerEvents: "none",
            whiteSpace: "nowrap",
          }}
        >
          <Text size="xs" c="dimmed">
            {point.title}
          </Text>
          <Text size="sm" fw={700}>
            {formatNumber(point.value, 0)} {unit}
          </Text>
        </Paper>
      )}
    </div>
  );
}
