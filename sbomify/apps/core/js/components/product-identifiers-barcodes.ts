import Alpine from 'alpinejs';
import JsBarcode from 'jsbarcode';

/** Maps identifier types to JsBarcode format names */
const FORMAT_MAP: Record<string, string> = {
  'gtin_12': 'UPC',
  'gtin_13': 'EAN13',
  'gtin_14': 'ITF14',
  'gtin_8': 'EAN8'
};

/**
 * Default barcode rendering configuration.
 *
 * Height 60 with reduced margins (textMargin: 6, margin: 4) is tuned to:
 * - Keep the barcode large enough for reliable scanning
 * - Fit into the compressed product identifier card layout
 * - Balance visual prominence with space efficiency
 */
const BARCODE_CONFIG = {
  width: 2,
  height: 60,
  displayValue: true,
  fontSize: 14,
  fontOptions: 'bold',
  font: 'monospace',
  textMargin: 6,
  textAlign: 'center' as const,
  textPosition: 'bottom' as const,
  margin: 4,
  background: '#ffffff',
  lineColor: '#000000'
};

export function registerProductIdentifiersBarcodes(): void {
  Alpine.data('productIdentifiersBarcodes', () => ({
    barcodeRendered: {} as Record<string, boolean>,
    barcodeErrors: {} as Record<string, boolean>,

    async renderBarcode(id: string, value: string, type: string): Promise<void> {
      // Skip if already rendered or errored
      if (this.barcodeRendered[id] || this.barcodeErrors[id]) return;

      // Initialize state
      this.barcodeRendered[id] = false;
      this.barcodeErrors[id] = false;

      try {
        // Get the barcode format based on type
        const format = FORMAT_MAP[type] || 'EAN13';

        // Wait a tick for DOM to be ready
        await this.$nextTick();

        // Find the SVG element
        const svg = document.querySelector(`[data-barcode-id="${id}"]`) as SVGElement | null;
        if (!svg) {
          console.warn(`No SVG element found for barcode ID: ${id}`);
          this.barcodeErrors[id] = true;
          return;
        }

        // Validate barcode value
        if (!value || value.trim() === '') {
          throw new Error('Empty barcode value');
        }

        // Render the barcode
        JsBarcode(svg, value, {
          format: format,
          ...BARCODE_CONFIG
        });

        this.barcodeRendered[id] = true;
        this.barcodeErrors[id] = false;

      } catch (err) {
        console.warn(`Failed to generate barcode for ${type}: ${value}`, err);
        this.barcodeErrors[id] = true;
        this.barcodeRendered[id] = false;
      }
    }
  }));
}
