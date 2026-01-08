import Alpine from 'alpinejs';
import JsBarcode from 'jsbarcode';

const FORMAT_MAP: Record<string, string> = {
  'gtin_12': 'UPC',
  'gtin_13': 'EAN13',
  'gtin_14': 'ITF14',
  'gtin_8': 'EAN8'
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
          width: 2,
          height: 50,
          displayValue: true,
          fontSize: 14,
          fontOptions: 'bold',
          font: 'monospace',
          textMargin: 8,
          textAlign: 'center',
          textPosition: 'bottom',
          margin: 10,
          background: '#ffffff',
          lineColor: '#000000'
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
