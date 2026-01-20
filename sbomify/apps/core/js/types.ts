// Shared types for component metadata and related structures

export interface ContactInfo {
    name: string;
    email: string;
    phone: string;
}

export interface SupplierInfo {
    name: string | null;
    url: string[] | null;
    address: string | null;
    contacts: ContactInfo[];
}

export interface CustomLicense {
    name: string;
    url: string | null;
    text: string | null;
}

export interface ContactProfile {
    id: string;
    name: string;
    is_default?: boolean;
    company?: string;
    supplier_name?: string;
    vendor?: string;
    email?: string;
    phone?: string;
    address?: string;
    website_urls?: string[];
    contacts?: ContactInfo[];
    authors?: ContactInfo[];
}

export interface ComponentMetaInfo {
    id: string;
    name: string;
    supplier: SupplierInfo;
    authors: ContactInfo[];
    licenses: (string | CustomLicense)[];
    lifecycle_phase: string | null;
    contact_profile_id: string | null;
    contact_profile: ContactProfile | null;
    uses_custom_contact: boolean;
    // Lifecycle event fields (aligned with Common Lifecycle Enumeration)
    release_date: string | null;
    end_of_support: string | null;
    end_of_life: string | null;
}
