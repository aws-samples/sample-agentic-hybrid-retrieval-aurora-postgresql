import { TRAIL, ageStyle, settle } from "./softReveal";
import { sourceAnchor } from "./citations";

export interface MdNode {
  type: string;
  value?: string;
  children?: MdNode[];
  position?: { start: { offset?: number } };
  data?: Record<string, unknown>;
}

const CITATION = /\[(\d+)\]/g;
const LITERAL = new Set(["code", "inlineCode", "html"]);

function trailChar(char: string, age: number): MdNode {
  return {
    type: "emphasis",
    data: { hName: "span", hProperties: { className: ["ask-fresh"], style: ageStyle(age) } },
    children: [{ type: "text", value: char }],
  };
}

/** The settled part of a run of text stays plain; only the last `TRAIL` characters are drawn faint. */
function ageChars(text: string, start: number, reveal: number): MdNode[] {
  const settledEnd = Math.max(0, Math.min(text.length, reveal - TRAIL - start));
  const nodes: MdNode[] = settledEnd ? [{ type: "text", value: text.slice(0, settledEnd) }] : [];
  for (let index = settledEnd; index < text.length; index += 1) {
    nodes.push(trailChar(text[index], reveal - 1 - (start + index)));
  }
  return nodes;
}

function citationChip(number: number, age: number, answerId: string): MdNode {
  const faint = age < TRAIL ? { style: `opacity:${(0.3 + 0.7 * settle(age)).toFixed(2)};` } : {};
  return {
    type: "emphasis",
    data: {
      hName: "a",
      hProperties: {
        className: ["ask-answer-cite"],
        href: `#${sourceAnchor(answerId, number)}`,
        dataSource: String(number),
        ...faint,
      },
    },
    children: [{ type: "text", value: String(number) }],
  };
}

function splitText(node: MdNode, reveal: number, numbers: Set<number>, answerId: string): MdNode[] {
  const value = node.value ?? "";
  const base = node.position?.start.offset ?? 0;
  const pieces: MdNode[] = [];
  let cursor = 0;
  for (const match of value.matchAll(CITATION)) {
    const number = Number(match[1]);
    if (!numbers.has(number)) continue;
    pieces.push(...ageChars(value.slice(cursor, match.index), base + cursor, reveal));
    pieces.push(citationChip(number, reveal - 1 - (base + match.index), answerId));
    cursor = match.index + match[0].length;
  }
  pieces.push(...ageChars(value.slice(cursor), base + cursor, reveal));
  return pieces;
}

/**
 * Turns the answer's text nodes into the soft reveal, in place.
 *
 * Each character carries its age on the answer's clock, so characters arrive
 * faint and darken over `TRAIL` characters; a `[n]` that names a real citation
 * becomes the same chip the sources list answers to, fading with them. Age is
 * read from each node's source offset, which spans formatting and paragraphs.
 */
export function ageText(tree: MdNode, reveal: number, numbers: Set<number>, answerId: string): void {
  if (!tree.children) return;
  tree.children = tree.children.flatMap((child) => {
    if (child.type === "text") return splitText(child, reveal, numbers, answerId);
    if (!LITERAL.has(child.type)) ageText(child, reveal, numbers, answerId);
    return [child];
  });
}
