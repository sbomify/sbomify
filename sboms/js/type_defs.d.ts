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

export interface SupplierInfo {
  name: string | null;
  url: string | null;
  address: string | null;
  contacts: ContactInfo[];
}

export interface ComponentMetaInfo {
  supplier: SupplierInfo;
  authors: ContactInfo[];
  licenses: (string | CustomLicense)[];
  lifecycle_phase: LifecyclePhase | null;
}

export interface AlertMessage {
  alertType: string | null;
  title: string | null;
  message: string | null;
}

export interface UserItemsResponse {
  team_key: string;
  team_name: string;
  item_key: string;
  item_name: string;
}

export interface ComponentUpload {
  id: string;
  name: string;
  timestamp: string;
  component_id: string;
  component_name: string;
  sbom_id: string;
  sbom_name: string;
  sbom_version: string;
  sbom_created_at: string;
}

export interface DashboardStats {
  total_components: number;
  total_public_components: number;
  total_private_components: number;
  total_users: number;
  total_products: number;
  total_projects: number;
  component_uploads: ComponentUpload[];
  license_count: Record<string, number>;
}
