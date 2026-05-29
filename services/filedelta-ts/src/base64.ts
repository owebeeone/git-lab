const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
const reverse = new Map<string, number>(
  Array.from(alphabet, (char, index) => [char, index]),
);

export function decodeBase64Payload(value: unknown): Uint8Array {
  if (typeof value !== "string" || !value.startsWith("base64:")) {
    throw new Error("payload must be a base64: string");
  }
  const encoded = value.slice("base64:".length);
  if (encoded.length % 4 !== 0) {
    throw new Error("invalid base64 length");
  }

  let padding = 0;
  if (encoded.endsWith("==")) {
    padding = 2;
  } else if (encoded.endsWith("=")) {
    padding = 1;
  }

  const outputLength = (encoded.length / 4) * 3 - padding;
  const output = new Uint8Array(outputLength);
  let outputOffset = 0;

  for (let offset = 0; offset < encoded.length; offset += 4) {
    const chars = encoded.slice(offset, offset + 4);
    const values = Array.from(chars, (char, index) => {
      if (char === "=") {
        if (offset + index < encoded.length - padding) {
          throw new Error("invalid base64 padding");
        }
        return 0;
      }
      const value = reverse.get(char);
      if (value === undefined) {
        throw new Error("invalid base64 character");
      }
      return value;
    });

    const triple = (values[0] << 18) | (values[1] << 12) | (values[2] << 6) | values[3];
    if (outputOffset < outputLength) output[outputOffset++] = (triple >> 16) & 0xff;
    if (outputOffset < outputLength) output[outputOffset++] = (triple >> 8) & 0xff;
    if (outputOffset < outputLength) output[outputOffset++] = triple & 0xff;
  }

  return output;
}
