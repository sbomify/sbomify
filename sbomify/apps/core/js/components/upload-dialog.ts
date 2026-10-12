/** Both artifact uploaders accept the same action and deep link, including older SBOM links. */
export function uploadDialog() {
    return {
        uploadOpen: false,
        init() {
            this.openFromHash();
        },
        openFromHash() {
            if (['#upload-artifact', '#upload-sbom'].includes(window.location.hash)) {
                this.uploadOpen = true;
            }
        },
    };
}
