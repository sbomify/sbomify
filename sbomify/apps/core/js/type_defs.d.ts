import { LifecyclePhase } from './enums';

export interface CustomLicense {
  name: string | null;
  url: string | null;
  text: string | null;
}

export interface ContactInfo {
  name: string | null;
  email: string | null;
  phone: string | null;
}

export interface ContactProfile {
  id: string;
  name: string;
  company: string | null;
  supplier_name: string | null;
  vendor: string | null;
  email: string | null;
  phone: string | null;
  address: string | null;
  website_urls: string[];
  contacts: ContactInfo[];
  is_default: boolean;
  created_at?: string;
  updated_at?: string;
}

export interface SupplierInfo {
  name: string | null;
  url: string[] | null;
  address: string | null;
  contacts: ContactInfo[];
}

export interface ComponentMetaInfo {
  id: string;
  name: string;
  supplier: SupplierInfo;
  authors: ContactInfo[];
  licenses: (string | CustomLicense)[];
  lifecycle_phase: LifecyclePhase | null;
  contact_profile_id: string | null;
  contact_profile?: ContactProfile | null;
  uses_custom_contact?: boolean;
}

export interface UserItemsResponse {
  team_key: string;
  team_name: string;
  item_key: string;
  item_name: string;
}

export interface DashboardSBOMUploadInfo {
  component_name: string;
  sbom_name: string;
  sbom_version?: string | null;
  created_at: string;
}


export interface AlertMessage {
  alertType: string | null;
  title: string | null;
  message: string | null;
}
