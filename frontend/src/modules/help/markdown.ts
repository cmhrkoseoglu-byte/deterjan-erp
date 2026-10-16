// Kılavuz Markdown'unu bloklara ayırır (Markdown.tsx çizer).

export type Block =
  | { kind: "h"; level: 1 | 2 | 3; text: string }
  | { kind: "p"; text: string }
  | { kind: "ul" | "ol"; items: string[] }
  | { kind: "note"; text: string }
  | { kind: "img"; alt: string; src: string };

export function parseMarkdown(source: string): Block[] {
  const blocks: Block[] = [];
  let paragraph: string[] = [];
  const flush = () => {
    if (paragraph.length) blocks.push({ kind: "p", text: paragraph.join(" ") });
    paragraph = [];
  };
  for (const raw of source.split("\n")) {
    const line = raw.trimEnd();
    const heading = /^(#{1,3})\s+(.*)$/.exec(line);
    const image = /^!\[([^\]]*)\]\(([^)]+)\)$/.exec(line.trim());
    const bullet = /^\s*[-*]\s+(.*)$/.exec(line);
    const numbered = /^\s*\d+[.)]\s+(.*)$/.exec(line);
    const last = blocks[blocks.length - 1];
    if (!line.trim()) {
      flush();
    } else if (heading) {
      flush();
      blocks.push({ kind: "h", level: heading[1].length as 1 | 2 | 3, text: heading[2] });
    } else if (image) {
      flush();
      blocks.push({ kind: "img", alt: image[1], src: image[2] });
    } else if (line.startsWith(">")) {
      flush();
      const text = line.replace(/^>\s?/, "");
      if (last?.kind === "note") last.text += ` ${text}`;
      else blocks.push({ kind: "note", text });
    } else if (bullet || numbered) {
      flush();
      const kind = bullet ? "ul" : "ol";
      const text = (bullet ?? numbered)![1];
      if (last?.kind === kind) last.items.push(text);
      else blocks.push({ kind, items: [text] });
    } else if (
      /^\s{2,}\S/.test(raw) &&
      (last?.kind === "ul" || last?.kind === "ol") &&
      !paragraph.length
    ) {
      last.items[last.items.length - 1] += ` ${line.trim()}`;
    } else {
      paragraph.push(line.trim());
    }
  }
  flush();
  return blocks;
}
