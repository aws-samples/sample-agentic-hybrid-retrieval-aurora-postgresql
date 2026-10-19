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

/** The class whose one-time entrance fades a newly revealed chunk in. */
export const REVEAL_CHUNK = "reveal-chunk";

function plain(value: string): MdNode[] {
  return value ? [{ type: "text", value }] : [];
}

function fading(value: string): MdNode {
  return {
    type: "emphasis",
    data: { hName: "span", hProperties: { className: [REVEAL_CHUNK] } },
    children: [{ type: "text", value }],
  };
}

/**
 * A run of text starting at source offset `start`, split where each revealed
 * chunk begins. Earlier pieces keep their place and their element, so only the
 * newest chunk mounts, and only it plays the entrance.
 */
function chunkPieces(text: string, start: number, chunks: readonly number[]): MdNode[] {
  if (!chunks.length || !text) return plain(text);
  const end = start + text.length;
  const cuts = chunks.filter((offset) => offset > start && offset < end).map((offset) => offset - start);
  const bounds = [0, ...cuts, text.length];
  return bounds.slice(0, -1).map((from, index) => fading(text.slice(from, bounds[index + 1])));
}

function citationChip(number: number, answerId: string, fades: boolean): MdNode {
  return {
    type: "emphasis",
    data: {
      hName: "a",
      hProperties: {
        className: fades ? ["ask-answer-cite", REVEAL_CHUNK] : ["ask-answer-cite"],
        href: `#${sourceAnchor(answerId, number)}`,
        dataSource: String(number),
      },
    },
    children: [{ type: "text", value: String(number) }],
  };
}

function splitText(node: MdNode, chunks: readonly number[], numbers: Set<number>, answerId: string): MdNode[] {
  const value = node.value ?? "";
  const base = node.position?.start.offset ?? 0;
  const pieces: MdNode[] = [];
  let cursor = 0;
  for (const match of value.matchAll(CITATION)) {
    const number = Number(match[1]);
    if (!numbers.has(number)) continue;
    pieces.push(...chunkPieces(value.slice(cursor, match.index), base + cursor, chunks));
    pieces.push(citationChip(number, answerId, chunks.length > 0));
    cursor = match.index + match[0].length;
  }
  pieces.push(...chunkPieces(value.slice(cursor), base + cursor, chunks));
  return pieces;
}

/**
 * Turns the answer's text nodes into revealed chunks and citation chips, in place.
 *
 * A `[n]` that names a real citation becomes the same chip the sources list
 * answers to. Chunk boundaries are source offsets, read from each node's
 * position, so a chunk that crosses formatting or a paragraph break still
 * splits at the right characters.
 */
export function revealText(tree: MdNode, chunks: readonly number[], numbers: Set<number>, answerId: string): void {
  if (!tree.children) return;
  tree.children = tree.children.flatMap((child) => {
    if (child.type === "text") return splitText(child, chunks, numbers, answerId);
    if (!LITERAL.has(child.type)) revealText(child, chunks, numbers, answerId);
    return [child];
  });
}
