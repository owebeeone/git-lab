export const LAB_DATA_MODE = ((import.meta as ImportMeta & { env?: { VITE_GL_DATA?: string } }).env?.VITE_GL_DATA ?? 'mock');
export const LAB_SERVICE_MODE = LAB_DATA_MODE === 'service';
export const LAB_HUB_PRESENCE = ((import.meta as ImportMeta & { env?: { VITE_GL_HUB_PRESENCE?: string } }).env?.VITE_GL_HUB_PRESENCE ?? '') === '1';
