export const MAX_FILE_SIZE_MB = 100;
export const MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024;

export const SUPPORTED_MIME_TYPES = [
  'image/gif',
  'image/webp',
  'image/png',
  'image/jpeg'
];

export interface ValidationResult {
  valid: boolean;
  error?: string;
}

export function validateUpload(file: File): ValidationResult {
  if (!SUPPORTED_MIME_TYPES.includes(file.type)) {
    return {
      valid: false,
      error: `Unsupported file type: ${file.type || 'unknown'}. Please upload GIF, WebP, PNG, or JPG.`
    };
  }

  if (file.size > MAX_FILE_SIZE_BYTES) {
    return {
      valid: false,
      error: `File too large: ${(file.size / 1024 / 1024).toFixed(1)}MB. Max size is ${MAX_FILE_SIZE_MB}MB.`
    };
  }

  return { valid: true };
}
