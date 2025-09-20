#!/usr/bin/env python3
"""
Script to update remaining hardcoded module paths in test files
"""
import os
import re
from pathlib import Path

def update_mock_paths():
    """Update mock/patch paths to use full Python paths"""
    
    # Define the mapping of old paths to new paths
    path_mappings = {
        # Core module references
        r'"core\.object_store\.': '"sbomify.apps.core.object_store.',
        r'"core\.views\.': '"sbomify.apps.core.views.',
        r'"core\.apis\.': '"sbomify.apps.core.apis.',
        r'"core\.models\.': '"sbomify.apps.core.models.',
        
        # SBOMs module references  
        r'"sboms\.apis\.': '"sbomify.apps.sboms.apis.',
        r'"sboms\.sbom_format_schemas\.': '"sbomify.apps.sboms.sbom_format_schemas.',
        
        # Billing module references
        r'"billing\.billing_processing\.': '"sbomify.apps.billing.billing_processing.',
        r'"billing\.views\.': '"sbomify.apps.billing.views.',
        r'"billing\.email_notifications\.': '"sbomify.apps.billing.email_notifications.',
        
        # Vulnerability scanning module references
        r'"vulnerability_scanning\.clients\.': '"sbomify.apps.vulnerability_scanning.clients.',
        
        # Documents module references
        r'"documents\.apis\.': '"sbomify.apps.documents.apis.',
        r'"documents\.views\.': '"sbomify.apps.documents.views.',
    }
    
    # Find all Python files in the sbomify directory
    sbomify_dir = Path("sbomify")
    python_files = list(sbomify_dir.rglob("*.py"))
    
    updated_files = []
    
    for file_path in python_files:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            original_content = content
            
            # Apply all path mappings
            for old_pattern, new_replacement in path_mappings.items():
                content = re.sub(old_pattern, new_replacement, content)
            
            # If content was modified, write it back
            if content != original_content:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                updated_files.append(str(file_path))
                print(f"Updated: {file_path}")
        
        except Exception as e:
            print(f"Error processing {file_path}: {e}")
    
    print(f"\nUpdated {len(updated_files)} files:")
    for file_path in updated_files:
        print(f"  - {file_path}")

if __name__ == "__main__":
    update_mock_paths() 