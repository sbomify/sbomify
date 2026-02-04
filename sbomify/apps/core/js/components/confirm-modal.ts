import Alpine from 'alpinejs';

type ConfirmType = 'warning' | 'danger' | 'info' | 'success';

interface ConfirmDetail {
  id?: string;
  title?: string;
  message?: string;
  type?: ConfirmType;
  confirmText?: string;
  cancelText?: string;
}

interface ConfirmModalData {
  show: boolean;
  id: string;
  title: string;
  message: string;
  type: ConfirmType;
  confirmText: string;
  cancelText: string;
  resolvePromise: ((value: boolean) => void) | null;
  openConfirm(detail: ConfirmDetail): Promise<boolean>;
  confirm(): void;
  cancel(): void;
  handleConfirmShow(detail: ConfirmDetail): void;
}

export function registerConfirmModal() {
  Alpine.data('confirmModal', (): ConfirmModalData => ({
    show: false,
    id: '',
    title: '',
    message: '',
    type: 'warning',
    confirmText: 'Confirm',
    cancelText: 'Cancel',
    resolvePromise: null,

    openConfirm(detail: ConfirmDetail): Promise<boolean> {
      this.id = detail.id || '';
      this.title = detail.title || 'Are you sure?';
      this.message = detail.message || '';
      this.type = detail.type || 'warning';
      this.confirmText = detail.confirmText || 'Confirm';
      this.cancelText = detail.cancelText || 'Cancel';
      this.show = true;

      return new Promise((resolve) => {
        this.resolvePromise = resolve;
      });
    },

    confirm(): void {
      this.show = false;
      if (this.resolvePromise) {
        this.resolvePromise(true);
        this.resolvePromise = null;
      }
    },

    cancel(): void {
      this.show = false;
      if (this.resolvePromise) {
        this.resolvePromise(false);
        this.resolvePromise = null;
      }
    },

    handleConfirmShow(detail: ConfirmDetail): void {
      this.openConfirm(detail).then((result) => {
        (this as unknown as { $dispatch: (name: string, data: object) => void }).$dispatch('confirm:result', {
          id: this.id,
          confirmed: result,
        });
      });
    },
  }));
}
