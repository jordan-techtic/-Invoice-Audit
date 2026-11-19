import { randomBytes } from "node:crypto";
import { deflateSync } from "node:zlib";

function crc32(buf: Buffer): number {
  let c, crc = 0xffffffff;
  for (let n = 0; n < buf.length; n++) {
    c = (crc ^ buf[n]) & 0xff;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    crc = (crc >>> 8) ^ c;
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function chunk(type: string, data: Buffer): Buffer {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length);
  const body = Buffer.concat([Buffer.from(type, "ascii"), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(body));
  return Buffer.concat([len, body, crc]);
}

/** A small valid RGB PNG that looks like a page of text lines; `seed` makes every file's bytes differ. */
export function makePng(seed: number, w = 360, h = 480): Buffer {
  // Random block so every generated file has unique bytes (and a unique SHA-256) across runs.
  const noise = randomBytes(2048);
  const rows: Buffer[] = [];
  for (let y = 0; y < h; y++) {
    const row = Buffer.alloc(1 + w * 3, 255);
    row[0] = 0;
    const line = y % 24 > 8 && y % 24 < 14 && y > 40;
    for (let x = 0; x < w; x++) {
      let v = 255;
      if (line && x > 30 && x < w - 30 - ((y * 7 + seed * 13) % 120)) v = 120 + ((x * seed) % 40);
      if (y >= 30 && y < 38 && x > 30 && x < 130) v = noise[(y * w + x) % noise.length];
      if (y < 30) v = 31 + (seed % 20);
      row[1 + x * 3] = v; row[2 + x * 3] = v; row[3 + x * 3] = y < 30 ? 86 : v;
    }
    rows.push(row);
  }
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(w, 0); ihdr.writeUInt32BE(h, 4); ihdr[8] = 8; ihdr[9] = 2;
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", ihdr), chunk("IDAT", deflateSync(Buffer.concat(rows))), chunk("IEND", Buffer.alloc(0)),
  ]);
}
