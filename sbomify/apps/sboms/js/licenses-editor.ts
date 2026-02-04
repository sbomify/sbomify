import Alpine from '../../core/js/alpine-init';
import { getCsrfToken } from '../../core/js/csrf';
import type { CustomLicense } from '../../core/js/types';

import { getFilteredLicenses, type LicenseInfo } from './licenses-utils';

interface LicenseTag {
    value: string | CustomLicense;
    displayValue: string;
    isInvalid: boolean;
    isCustom: boolean;
}

interface LicensesEditorProps {
    licenses: (string | CustomLicense)[];
    unknownTokens: string[];
}

export function registerLicensesEditor() {
    Alpine.data('licensesEditor', (props: LicensesEditorProps) => ({
        licenseTags: [] as LicenseTag[],
        licenseExpression: '',
        validationError: '',
        showSuggestions: false,
        selectedIndex: -1,
        licenses: [] as LicenseInfo[],
        showCustomLicenseForm: false,
        editingCustomLicense: false,
        editingIndex: -1,
        showCustomLicenseSuccess: false,
        unknownTokens: props.unknownTokens || [],
        customLicense: {
            name: '',
            url: '',
            text: ''
        },
        formErrors: {} as Record<string, string>,
        boundMetadataLoadedHandler: null as ((e: Event) => void) | null,

        init() {
            this.initializeTags(props.licenses || []);
            this.loadLicenses();

            if (this.unknownTokens.length > 0) {
                this.customLicense.name = '';
                this.showCustomLicenseForm = true;
            }

            this.boundMetadataLoadedHandler = (e: Event) => {
                const detail = (e as CustomEvent).detail;
                if (detail && detail.licenses) {
                    this.initializeTags(detail.licenses);
                }
            };
            window.addEventListener('component:metadata:loaded', this.boundMetadataLoadedHandler);
        },

        destroy() {
            if (this.boundMetadataLoadedHandler) {
                window.removeEventListener('component:metadata:loaded', this.boundMetadataLoadedHandler);
                this.boundMetadataLoadedHandler = null;
            }
        },

        initializeTags(licenses: (string | CustomLicense)[]) {
            this.licenseTags = licenses.map(lic => {
                if (typeof lic === 'string') {
                    return {
                        value: lic,
                        displayValue: lic,
                        isInvalid: false,
                        isCustom: false
                    };
                } else {
                    return {
                        value: lic,
                        displayValue: lic.name || 'Unnamed License',
                        isInvalid: false,
                        isCustom: true
                    };
                }
            }).filter(tag => tag.displayValue.length > 0);
        },

        async loadLicenses() {
            try {
                const response = await fetch('/api/v1/licensing/licenses');
                if (response.ok) {
                    this.licenses = await response.json();
                }
            } catch {
            }
        },

        get filteredLicenses(): LicenseInfo[] {
            return getFilteredLicenses(this.licenseExpression, this.licenses);
        },

        onInput() {
            this.showSuggestions = true;
            this.selectedIndex = -1;
        },

        handleKeyDown(e: KeyboardEvent) {


            if (e.key === 'Enter' && (!this.showSuggestions || this.selectedIndex < 0)) {
                e.preventDefault();
                this.addCurrentExpression();
                return;
            }

            if (!this.showSuggestions || this.filteredLicenses.length === 0) return;

            if (e.key === 'ArrowDown') {
                e.preventDefault();
                this.selectedIndex = (this.selectedIndex + 1) % this.filteredLicenses.length;
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                this.selectedIndex = this.selectedIndex <= 0 ? this.filteredLicenses.length - 1 : this.selectedIndex - 1;
            } else if (e.key === 'Enter' && this.selectedIndex >= 0) {
                e.preventDefault();
                this.selectLicense(this.filteredLicenses[this.selectedIndex]);
            } else if (e.key === 'Escape') {
                this.showSuggestions = false;
                this.selectedIndex = -1;
            }
        },

        handleBlur() {
            this.showSuggestions = false;
            this.selectedIndex = -1;
        },

        selectLicense(license: LicenseInfo) {
            if (license.category === 'operator') {
                this.licenseExpression = this.licenseExpression.trim() + ' ' + license.key + ' ';
            } else {
                const operatorPattern = /\s+(AND|OR|WITH)\s+/gi;
                let lastOperatorEnd = 0;
                let match: RegExpExecArray | null;

                while ((match = operatorPattern.exec(this.licenseExpression)) !== null) {
                    lastOperatorEnd = match.index + match[0].length;
                }

                const beforeToken = this.licenseExpression.substring(0, lastOperatorEnd);
                this.licenseExpression = beforeToken + license.key;
            }

            this.showSuggestions = false;
            this.selectedIndex = -1;
        },

        addCurrentExpression() {
            let expression = this.licenseExpression.trim();
            if (!expression) return;

            // Normalize operators to uppercase (and -> AND, or -> OR, with -> WITH)
            expression = expression.replace(/\b(and|or|with)\b/gi, match => match.toUpperCase());

            const isDuplicate = this.licenseTags.some(tag => {
                const tagValue = typeof tag.value === 'string' ? tag.value : tag.value.name;
                return tagValue === expression;
            });

            if (!isDuplicate) {
                this.licenseTags.push({
                    value: expression,
                    displayValue: expression,
                    isInvalid: false,
                    isCustom: false
                });
                this.licenseExpression = '';
                this.dispatchUpdate();
                this.validateTag(expression, this.licenseTags.length - 1);
            }
        },

        removeTag(index: number) {
            this.licenseTags.splice(index, 1);
            this.dispatchUpdate();
        },

        async validateTag(tagValue: string, tagIndex: number) {
            try {
                const response = await fetch('/api/v1/licensing/license-expressions/validate', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': getCsrfToken()
                    },
                    body: JSON.stringify({ expression: tagValue })
                });

                if (response.ok) {
                    const result = await response.json();
                    if (result.status !== 200 && this.licenseTags[tagIndex]) {
                        this.licenseTags[tagIndex].isInvalid = true;
                    }
                } else {
                    if (this.licenseTags[tagIndex]) {
                        this.licenseTags[tagIndex].isInvalid = true;
                    }
                }
            } catch {
                // Validation failed silently - tag will remain valid
            }
        },

        editCustomLicense(index: number) {
            const tag = this.licenseTags[index];
            if (tag.isCustom && typeof tag.value === 'object') {
                this.editingCustomLicense = true;
                this.editingIndex = index;
                this.customLicense.name = tag.value.name || '';
                this.customLicense.url = tag.value.url || '';
                this.customLicense.text = tag.value.text || '';
                this.showCustomLicenseForm = true;
            }
        },

        closeCustomLicenseForm() {
            this.showCustomLicenseForm = false;
            this.editingCustomLicense = false;
            this.editingIndex = -1;
            this.customLicense = { name: '', url: '', text: '' };
            this.formErrors = {};
        },

        submitCustomLicense() {
            this.formErrors = {};

            const customLicenseData: CustomLicense = {
                name: this.customLicense.name,
                url: this.customLicense.url || null,
                text: this.customLicense.text || null
            };

            if (this.editingCustomLicense && this.editingIndex >= 0) {
                this.licenseTags[this.editingIndex] = {
                    value: customLicenseData,
                    displayValue: customLicenseData.name || 'Unnamed License',
                    isInvalid: false,
                    isCustom: true
                };
            } else {
                this.licenseTags.push({
                    value: customLicenseData,
                    displayValue: customLicenseData.name || 'Unnamed License',
                    isInvalid: false,
                    isCustom: true
                });
            }

            this.dispatchUpdate();
            this.showCustomLicenseSuccess = true;
            this.closeCustomLicenseForm();

            setTimeout(() => {
                this.showCustomLicenseSuccess = false;
            }, 3000);
        },

        dispatchUpdate() {
            const allLicenses: (string | CustomLicense)[] = this.licenseTags.map(tag => tag.value);
            if (this.licenseExpression.trim()) {
                allLicenses.push(this.licenseExpression.trim());
            }
            this.$dispatch('licenses-updated', { licenses: allLicenses });
        }
    }));
}
