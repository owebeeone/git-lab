declare module "node:fs" {
  export function readdirSync(path: string | URL): string[];
  export function readFileSync(path: string | URL): Uint8Array;
  export function readFileSync(path: string | URL, encoding: "utf8"): string;
}
