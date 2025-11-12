#!/usr/bin/env python3
"""
Product Editor/Creator - Tool for creating and editing products in Shopify
"""

import os
import sys
import requests
import json
import base64
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

# UTF-8 encoding handled at subprocess level in backend

# Add the parent directory to the path so we can import config
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from config import STORE_DOMAIN, ACCESS_TOKEN, API_VERSION
except ImportError:
    print("ERROR: Could not import config. Make sure config.py exists in the backend directory.")
    sys.exit(1)

def format_price(price):
    """Format price to 2 decimal places as string."""
    try:
        decimal_price = Decimal(str(price))
        formatted = decimal_price.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        return str(formatted)
    except (ValueError, TypeError):
        return str(price)

def manage_product_media(product_id, shopify_media_ids_to_keep):
    """
    Remove media from a product that are not in the keep list
    
    Args:
        product_id (int): The ID of the product
        shopify_media_ids_to_keep (list): List of media IDs (global IDs) to keep
    
    Returns:
        dict: Result with success status and any errors
    """
    try:
        print(f"🔄 Managing media for product {product_id}...")
        print(f"📋 Media IDs to keep: {shopify_media_ids_to_keep}")
        
        # Get existing product media
        url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/products/{product_id}.json"
        headers = {
            'X-Shopify-Access-Token': ACCESS_TOKEN,
            'Content-Type': 'application/json'
        }
        
        response = requests.get(url, headers=headers)
        if not response.ok:
            return {"success": False, "error": f"Failed to get product: {response.status_code}"}
        
        product_data = response.json().get('product', {})
        existing_media = product_data.get('images', [])
        
        print(f"📷 Found {len(existing_media)} existing media items")
        
        # Convert keep list to comparable format
        # We expect REST API numeric IDs (not global IDs) for comparison
        keep_ids = set()
        for media_id in shopify_media_ids_to_keep:
            if isinstance(media_id, str):
                if media_id.startswith('gid://'):
                    # Extract numeric ID from global ID
                    # NOTE: Global ID numeric part is DIFFERENT from REST API ID!
                    # For REST API comparison, we need the REST API numeric ID, not the global ID numeric
                    # But if only global ID is provided, try to extract it anyway
                    keep_ids.add(media_id.split('/')[-1])
                else:
                    # Direct REST API numeric ID (what we want)
                    keep_ids.add(media_id)
            else:
                # Numeric ID converted to string
                keep_ids.add(str(media_id))
        
        print(f"🔑 Keep IDs (normalized): {keep_ids}")
        
        # Debug: Show all existing media IDs
        existing_ids = [str(img.get('id')) for img in existing_media]
        print(f"📋 Existing media IDs on product: {existing_ids}")
        
        # Find media to remove
        media_to_remove = []
        for media in existing_media:
            media_id = str(media.get('id'))
            if media_id not in keep_ids:
                media_to_remove.append(media_id)
                print(f"🗑️ Will remove media ID: {media_id} (not in keep list)")
            else:
                print(f"✅ Will keep media ID: {media_id}")
        
        if not media_to_remove:
            print(f"ℹ️ No media to remove - all {len(existing_media)} existing images are in the keep list")
        else:
            print(f"🗑️ Found {len(media_to_remove)} media items to remove: {media_to_remove}")
        
        # Remove unwanted media
        removed_count = 0
        errors = []
        
        for media_id in media_to_remove:
            try:
                delete_url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/products/{product_id}/images/{media_id}.json"
                print(f"🗑️ Attempting to delete image {media_id} from product {product_id}...")
                delete_response = requests.delete(delete_url, headers=headers)
                
                if delete_response.ok or delete_response.status_code == 204:
                    removed_count += 1
                    print(f"✅ Successfully removed media ID: {media_id}")
                else:
                    error_msg = f"Failed to remove media {media_id}: {delete_response.status_code}"
                    if delete_response.text:
                        error_msg += f" - {delete_response.text[:200]}"
                    errors.append(error_msg)
                    print(f"❌ {error_msg}")
            except Exception as e:
                error_msg = f"Error removing media {media_id}: {str(e)}"
                errors.append(error_msg)
                print(f"💥 {error_msg}")
                import traceback
                print(traceback.format_exc())
        
        return {
            "success": len(errors) == 0,
            "removed_count": removed_count,
            "errors": errors
        }
        
    except Exception as e:
        error_msg = f"Error managing product media: {str(e)}"
        print(f"💥 {error_msg}")
        return {
            "success": False,
            "removed_count": 0,
            "errors": [error_msg]
        }

def reorder_product_media_by_order(product_id, media_order, shopify_media_ids):
    """
    Reorder product media according to the media_order array from frontend
    This includes both newly uploaded files and existing Shopify media
    
    Args:
        product_id (int): The ID of the product
        media_order (list): List of media order items like [{'type': 'upload', 'index': 0}, {'type': 'shopify', 'id': '...', 'position': 1}]
        shopify_media_ids (list): List of Shopify media IDs that were kept (for reference)
    
    Returns:
        dict: Result with success status
    """
    try:
        if not media_order:
            return {"success": True, "message": "No media order specified"}
        
        print(f"🔄 Reordering media by order for product {product_id}...")
        
        # Get current product media
        url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/products/{product_id}.json"
        headers = {
            'X-Shopify-Access-Token': ACCESS_TOKEN,
            'Content-Type': 'application/json'
        }
        
        response = requests.get(url, headers=headers)
        if not response.ok:
            return {"success": False, "error": f"Failed to get product: {response.status_code}"}
        
        product_data = response.json().get('product', {})
        existing_images = product_data.get('images', [])
        
        print(f"📷 Found {len(existing_images)} existing images on product")
        
        # Normalize shopify_media_ids for comparison
        normalized_keep_ids = set()
        for media_id in (shopify_media_ids or []):
            if isinstance(media_id, str) and media_id.startswith('gid://'):
                normalized_keep_ids.add(media_id.split('/')[-1])
            else:
                normalized_keep_ids.add(str(media_id))
        
        # Separate existing images from newly uploaded images
        existing_image_ids = set(str(img.get('id')) for img in existing_images if str(img.get('id')) in normalized_keep_ids)
        
        # Identify newly uploaded images (not in the keep list)
        # These are images that were just uploaded and weren't in the original keep list
        new_upload_images = [
            img for img in existing_images 
            if str(img.get('id')) not in normalized_keep_ids
        ]
        # Sort new uploads by creation time or ID (oldest/newest uploads first)
        # If created_at is available, sort by it (ascending = oldest first)
        # Otherwise sort by ID (ascending)
        new_upload_images.sort(key=lambda x: (
            x.get('created_at', '') if x.get('created_at') else '',
            x.get('id', 0)
        ))
        new_upload_ids = [str(img.get('id')) for img in new_upload_images]
        
        # Also create a map of all image IDs for quick lookup
        all_image_map = {str(img.get('id')): img for img in existing_images}
        
        all_image_ids = [str(img.get('id')) for img in existing_images]
        
        # Count how many new uploads we expect
        upload_count = sum(1 for item in media_order if item.get('type') == 'upload')
        shopify_count = sum(1 for item in media_order if item.get('type') == 'shopify')
        
        print(f"📊 Media order: {upload_count} uploads, {shopify_count} Shopify media")
        print(f"📊 Found {len(new_upload_ids)} newly uploaded images")
        
        # Map media order to actual image IDs
        position_map = {}  # Maps desired position -> image ID
        shopify_positions_processed = 0
        upload_positions_processed = 0
        
        for order_item in media_order:
            item_type = order_item.get('type')
            # Use position from order_item if provided, otherwise use sequential position
            position = order_item.get('position')
            if position is None:
                position = len(position_map) + 1
            
            if item_type == 'shopify':
                # Match by Shopify ID
                media_id = str(order_item.get('id', ''))
                # Check in the all_image_map for quick lookup
                if media_id in all_image_map:
                    position_map[position] = media_id
                    shopify_positions_processed += 1
                    print(f"📍 Position {position}: Shopify media ID {media_id}")
                else:
                    print(f"⚠️ Could not find Shopify media ID {media_id} in product images")
                    print(f"   Available image IDs: {list(all_image_map.keys())[:10]}...")  # Show first 10 for debugging
            elif item_type == 'upload':
                # Match newly uploaded images by order
                if upload_positions_processed < len(new_upload_ids):
                    image_id = new_upload_ids[upload_positions_processed]
                    position_map[position] = image_id
                    upload_positions_processed += 1
                    print(f"📍 Position {position}: New upload (image ID {image_id})")
                else:
                    print(f"⚠️ Could not find upload at index {upload_positions_processed} (only {len(new_upload_ids)} new uploads found)")
        
        # Verify we have all expected images before reordering
        missing_images = []
        for order_item in media_order:
            if order_item.get('type') == 'shopify':
                media_id = str(order_item.get('id', ''))
                if media_id not in all_image_map:
                    missing_images.append(media_id)
        
        if missing_images:
            print(f"⚠️ Warning: {len(missing_images)} expected images not found. Attempting to continue with available images.")
        
        # Update positions for all images
        errors = []
        successful_updates = []
        for position, image_id in sorted(position_map.items()):
            update_url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/products/{product_id}/images/{image_id}.json"
            payload = {
                "image": {
                    "id": int(image_id),
                    "position": position
                }
            }
            
            update_response = requests.put(update_url, headers=headers, json=payload)
            if update_response.ok:
                successful_updates.append((position, image_id))
                print(f"✅ Set position {position} for image ID: {image_id}")
            else:
                error_msg = f"Failed to reorder image {image_id}: {update_response.status_code} - {update_response.text[:200]}"
                errors.append(error_msg)
                print(f"❌ {error_msg}")
        
        print(f"📊 Reordering summary: {len(successful_updates)} successful, {len(errors)} errors")
        
        return {
            "success": len(errors) == 0,
            "errors": errors
        }
        
    except Exception as e:
        error_msg = f"Error reordering product media by order: {str(e)}"
        print(f"💥 {error_msg}")
        return {
            "success": False,
            "errors": [error_msg]
        }

def reorder_product_media(product_id, shopify_media_ids_in_order):
    """
    Reorder product media according to the specified order
    
    Args:
        product_id (int): The ID of the product
        shopify_media_ids_in_order (list): List of media IDs in desired order
    
    Returns:
        dict: Result with success status
    """
    try:
        if not shopify_media_ids_in_order:
            return {"success": True, "message": "No media to reorder"}
        
        print(f"🔄 Reordering {len(shopify_media_ids_in_order)} media items for product {product_id}...")
        
        # Get existing product media
        url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/products/{product_id}.json"
        headers = {
            'X-Shopify-Access-Token': ACCESS_TOKEN,
            'Content-Type': 'application/json'
        }
        
        response = requests.get(url, headers=headers)
        if not response.ok:
            return {"success": False, "error": f"Failed to get product: {response.status_code}"}
        
        product_data = response.json().get('product', {})
        existing_images = product_data.get('images', [])
        
        # Create a mapping of image IDs to their data
        image_map = {str(img.get('id')): img for img in existing_images}
        
        # Update positions for each image
        errors = []
        for position, media_id in enumerate(shopify_media_ids_in_order, start=1):
            # Normalize media ID
            if isinstance(media_id, str) and media_id.startswith('gid://'):
                media_id = media_id.split('/')[-1]
            media_id = str(media_id)
            
            if media_id in image_map:
                image_id = image_map[media_id]['id']
                update_url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/products/{product_id}/images/{image_id}.json"
                payload = {
                    "image": {
                        "id": image_id,
                        "position": position
                    }
                }
                
                update_response = requests.put(update_url, headers=headers, json=payload)
                if update_response.ok:
                    print(f"✅ Set position {position} for media ID: {media_id}")
                else:
                    error_msg = f"Failed to reorder media {media_id}: {update_response.status_code}"
                    errors.append(error_msg)
                    print(f"❌ {error_msg}")
        
        return {
            "success": len(errors) == 0,
            "errors": errors
        }
        
    except Exception as e:
        error_msg = f"Error reordering product media: {str(e)}"
        print(f"💥 {error_msg}")
        return {
            "success": False,
            "errors": [error_msg]
        }

def upload_media_to_product(product_id, media_files, shopify_media_ids=None, product_name=None, product_sku=None):
    """
    Upload media files (images/videos) to a Shopify product using the correct API
    
    Args:
        product_id (int): The ID of the product to add media to
        media_files (list): List of media file dictionaries with filename, content, and content_type
        shopify_media_ids (list): List of existing Shopify media file IDs to attach to the product
        product_name (str): The product name for file naming (format: {product_name}_{x})
    
    Returns:
        dict: Result with success status and any errors
    """
    try:
        total_media = len(media_files) + (len(shopify_media_ids) if shopify_media_ids else 0)
        
        if total_media == 0:
            return {"success": True, "message": "No media files to upload"}
        
        print(f"🔄 Uploading {len(media_files)} new files and attaching {len(shopify_media_ids) if shopify_media_ids else 0} existing files to product {product_id}")
        
        success_count = 0
        errors = []
        
        # Helper to sanitize parts for filenames
        def _sanitize(value):
            s = "" if value is None else str(value)
            # allow letters, numbers, space, dash, underscore
            s = "".join(c for c in s if c.isalnum() or c in (' ', '-', '_')).rstrip()
            s = s.replace(' ', '_')
            while '__' in s:
                s = s.replace('__', '_')
            return s[:120] if s else ''

        # Upload new media files
        for i, media_file in enumerate(media_files):
            try:
                original_filename = media_file['filename']
                content = media_file['content']
                content_type = media_file['content_type']
                
                # Create new filename with SKU, product name and position: {SKU}_{product name}_{x}
                clean_name = _sanitize(product_name or '')
                clean_sku = _sanitize(product_sku or '') or 'NOSKU'
                file_extension = original_filename.split('.')[-1] if '.' in original_filename else ''
                base = f"{clean_sku}_{clean_name}_{i+1}" if clean_name else f"{clean_sku}_{i+1}"
                filename = f"{base}.{file_extension}" if file_extension else base
                
                # Determine if it's an image or video
                is_video = content_type.startswith('video/')
                media_type = 'video' if is_video else 'image'
                
                # Use the correct Shopify API endpoint for product media
                if is_video:
                    # For videos, use the product media endpoint
                    url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/products/{product_id}/media.json"
                    
                    # Create multipart form data for video upload
                    files = {
                        'media[attachment]': (filename, content, content_type)
                    }
                    data = {
                        'media[alt]': ''
                    }
                    
                    headers = {
                        "X-Shopify-Access-Token": ACCESS_TOKEN
                    }
                    
                    response = requests.post(url, headers=headers, files=files, data=data)
                    
                else:
                    # For images, use the product images endpoint
                    url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/products/{product_id}/images.json"
                    
                    # Create multipart form data for image upload
                    files = {
                        'image[attachment]': (filename, content, content_type)
                    }
                    data = {
                        'image[alt]': ''
                    }
                    
                    headers = {
                        "X-Shopify-Access-Token": ACCESS_TOKEN
                    }
                    
                    response = requests.post(url, headers=headers, files=files, data=data)
                
                if response.status_code in [200, 201]:
                    success_count += 1
                    response_data = response.json()
                    media_id = response_data.get('image', {}).get('id') or response_data.get('media', {}).get('id')
                    print(f"✅ Uploaded {media_type}: {filename} (ID: {media_id})")
                else:
                    error_msg = f"Failed to upload {media_type} {filename}: {response.status_code} - {response.text}"
                    errors.append(error_msg)
                    print(f"❌ {error_msg}")
                    
            except Exception as e:
                error_msg = f"Error uploading media file {filename}: {str(e)}"
                errors.append(error_msg)
                print(f"💥 {error_msg}")
        
        # Attach existing Shopify media files using GraphQL
        if shopify_media_ids:
            print(f"🔄 Attaching {len(shopify_media_ids)} existing Shopify media files to product {product_id}")
            
            try:
                # Use GraphQL to attach existing files to the product
                graphql_url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/graphql.json"
                headers = {
                    'X-Shopify-Access-Token': ACCESS_TOKEN,
                    'Content-Type': 'application/json',
                }
                
                # Convert product ID to Global ID format
                product_global_id = f"gid://shopify/Product/{product_id}"
                
                # Prepare file updates for each media ID
                file_updates = []
                for media_id in shopify_media_ids:
                    # Use the Global ID directly (it should already be in the correct format)
                    # If it's a numeric ID, convert it to Global ID format
                    if media_id.isdigit():
                        media_global_id = f"gid://shopify/GenericFile/{media_id}"
                    else:
                        media_global_id = media_id  # Already a Global ID
                    
                    file_updates.append({
                        "id": media_global_id,
                        "referencesToAdd": [product_global_id]
                    })
                
                # GraphQL mutation to attach files to product
                mutation = """
                mutation fileUpdate($input: [FileUpdateInput!]!) {
                    fileUpdate(files: $input) {
                        files {
                            id
                            alt
                        }
                        userErrors {
                            field
                            message
                        }
                    }
                }
                """
                
                variables = {
                    "input": file_updates
                }
                
                response = requests.post(graphql_url, json={'query': mutation, 'variables': variables}, headers=headers)
                
                if response.status_code == 200:
                    data = response.json()
                    
                    # Check for GraphQL errors
                    if 'errors' in data:
                        error_msg = f"GraphQL errors: {data['errors']}"
                        errors.append(error_msg)
                        print(f"❌ {error_msg}")
                    elif 'data' in data and 'fileUpdate' in data['data']:
                        result = data['data']['fileUpdate']
                        
                        if result.get('userErrors'):
                            for error in result['userErrors']:
                                error_msg = f"User error: {error.get('message', 'Unknown error')}"
                                errors.append(error_msg)
                                print(f"❌ {error_msg}")
                        
                        if result.get('files'):
                            success_count += len(result['files'])
                            for file in result['files']:
                                filename = file.get('alt', file.get('filename', 'Unknown'))
                                print(f"✅ Attached existing media: {filename}")
                        else:
                            error_msg = "No files were attached - check file IDs and permissions"
                            errors.append(error_msg)
                            print(f"❌ {error_msg}")
                    else:
                        error_msg = "Invalid response format from Shopify GraphQL"
                        errors.append(error_msg)
                        print(f"❌ {error_msg}")
                else:
                    error_msg = f"HTTP error: {response.status_code} - {response.text}"
                    errors.append(error_msg)
                    print(f"❌ {error_msg}")
                    
            except Exception as e:
                error_msg = f"Error attaching existing media files: {str(e)}"
                errors.append(error_msg)
                print(f"💥 {error_msg}")
        
        # Fetch product images after upload to get their IDs
        product_images = []
        if total_media > 0:
            try:
                get_url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/products/{product_id}.json"
                get_response = requests.get(get_url, headers=headers)
                if get_response.status_code == 200:
                    product_data = get_response.json().get("product", {})
                    product_images = product_data.get("images", [])
                    print(f"🔍 Fetched {len(product_images)} product images", flush=True)
            except Exception as e:
                print(f"⚠️ Failed to fetch product images: {e}", flush=True)
        
        return {
            "success": len(errors) == 0,
            "success_count": success_count,
            "errors": errors,
            "product_images": product_images  # Return product images for reference
        }
        
    except Exception as e:
        error_msg = f"Error uploading media files: {str(e)}"
        print(f"💥 {error_msg}")
        return {
            "success": False,
            "success_count": 0,
            "errors": [error_msg]
        }

def update_product_taxable(product_id, taxable):
    """
    Update the taxable field for a product's variants
    
    Args:
        product_id (int): The ID of the product to update
        taxable (bool): Whether the product should be taxable
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/products/{product_id}.json"
        headers = {
            "X-Shopify-Access-Token": ACCESS_TOKEN,
            "Content-Type": "application/json"
        }
        
        # First, get the current product to get existing variants
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            print(f"❌ Failed to get product for taxable update: {response.status_code}")
            return False
        
        product_data = response.json()["product"]
        variants = product_data.get("variants", [])
        
        # Update each variant with the taxable field
        for variant in variants:
            variant["taxable"] = taxable
        
        # Update the product with modified variants
        payload = {
            "product": {
                "id": product_id,
                "variants": variants
            }
        }
        
        update_response = requests.put(url, headers=headers, json=payload)
        if update_response.status_code == 200:
            response_data = update_response.json()
            updated_variants = response_data.get("product", {}).get("variants", [])
            print(f"✅ Updated taxable field to {taxable} for product {product_id}")
            return True
        else:
            print(f"❌ Failed to update taxable field: {update_response.status_code} - {update_response.text}")
            return False
            
    except Exception as e:
        print(f"💥 Error updating taxable field: {str(e)}")
        return False

def create_metafields(product_id, metafields_data):
    """
    Create metafields for a product
    
    Args:
        product_id (int): The ID of the product to add metafields to
        metafields_data (list): List of metafield data dictionaries
    
    Returns:
        dict: Result with success status and any errors
    """
    try:
        url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/products/{product_id}/metafields.json"
        headers = {
            "X-Shopify-Access-Token": ACCESS_TOKEN,
            "Content-Type": "application/json"
        }
        
        success_count = 0
        errors = []
        
        for metafield_data in metafields_data:
            try:
                # Normalize value formatting based on metafield type
                raw_value = metafield_data.get("value", "")
                mf_type = metafield_data.get("type", "single_line_text_field") or "single_line_text_field"

                # For list types, Shopify expects a JSON array string
                formatted_value = raw_value
                try:
                    if isinstance(raw_value, str) and raw_value.strip() and mf_type.startswith('list.'):
                        v = raw_value.strip()
                        # If not already a JSON array (simple heuristic), wrap it
                        is_json_array = (v.startswith('[') and v.endswith(']'))
                        formatted_value = v if is_json_array else json.dumps([v])
                except Exception:
                    # Fallback to raw value if formatting fails
                    formatted_value = raw_value
                
                # Replace blank/empty values with "-" (except for list types which should remain as JSON arrays)
                # Also skip if value is already a valid JSON array (for list types)
                if not mf_type.startswith('list.'):
                    # For non-list types, check if value is blank
                    if isinstance(formatted_value, str):
                        if not formatted_value.strip():
                            formatted_value = "-"
                    elif formatted_value is None or formatted_value == "":
                        formatted_value = "-"
                elif mf_type.startswith('list.'):
                    # For list types, only replace if it's an empty string (not a valid JSON array)
                    if isinstance(formatted_value, str):
                        stripped = formatted_value.strip()
                        if not stripped or stripped == '[]' or (not stripped.startswith('[') and not stripped):
                            formatted_value = json.dumps(["-"])

                payload = {
                    "metafield": {
                        "namespace": metafield_data.get("namespace", "custom"),
                        "key": metafield_data.get("key", ""),
                        "value": formatted_value,
                        "type": mf_type
                    }
                }
                
                response = requests.post(url, headers=headers, json=payload)
                
                if response.status_code in [200, 201]:
                    success_count += 1
                    print(f"✅ Created metafield: {metafield_data.get('namespace')}.{metafield_data.get('key')}")
                else:
                    error_msg = f"Failed to create metafield {metafield_data.get('namespace')}.{metafield_data.get('key')}: {response.status_code} - {response.text}"
                    errors.append(error_msg)
                    print(f"❌ {error_msg}")
                    
            except Exception as e:
                error_msg = f"Error creating metafield {metafield_data.get('namespace')}.{metafield_data.get('key')}: {str(e)}"
                errors.append(error_msg)
                print(f"💥 {error_msg}")
        
        return {
            "success": len(errors) == 0,
            "success_count": success_count,
            "errors": errors
        }
        
    except Exception as e:
        error_msg = f"Error creating metafields: {str(e)}"
        print(f"💥 {error_msg}")
        return {
            "success": False,
            "success_count": 0,
            "errors": [error_msg]
        }

def create_product(product_data):
    """
    Create a new product in Shopify using the Admin API, or update existing product if product_id is provided

    Args:
        product_data (dict): Product information including title, description, etc.

    Returns:
        dict: Result with success status and product information
    """
    try:
        # Check if we're updating an existing product
        existing_product_id = product_data.get("product_id")
        if existing_product_id:
            # Update existing product
            url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/products/{existing_product_id}.json"
            method = "PUT"
            print(f"🔄 Updating existing product {existing_product_id}")
        else:
            # Create new product
            url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/products.json"
            method = "POST"
            print(f"➕ Creating new product")

        headers = {
            "X-Shopify-Access-Token": ACCESS_TOKEN,
            "Content-Type": "application/json"
        }
        
        # Determine if product should be taxable based on VAT setting
        tags = product_data.get("tags", "")
        charge_vat_raw = product_data.get("charge_vat", True)  # Default to True if not provided
        
        # Convert to boolean if it's a string (from form data)
        if isinstance(charge_vat_raw, str):
            charge_vat = charge_vat_raw.lower() in ['true', '1', 'yes']
        else:
            charge_vat = bool(charge_vat_raw)
        
        taxable = charge_vat
        
        print(f"🏷️ Tags: {tags}")
        print(f"💰 Taxable setting: {taxable}")
        
        # Check if colours are provided
        product_colours = product_data.get("product_colours", "").strip()
        has_colours = bool(product_colours)
        
        # Prepare the product payload (without taxable field initially)
        payload = {
            "product": {
                "title": product_data.get("title", ""),
                "body_html": product_data.get("description", ""),
                "status": product_data.get("status", "active"),
                "tags": tags,
                "variants": [
                    {
                        "price": format_price(product_data.get("price", "0.00")),
                        "sku": product_data.get("sku", ""),
                        "inventory_quantity": product_data.get("inventory_quantity", 0),
                        "weight": product_data.get("weight", 0),
                        "requires_shipping": True
                    }
                ]
            }
        }
        
        # Debug: Print the description being saved
        description = product_data.get("description", "")
        print(f"🔍 Description being saved: {repr(description)}", flush=True)
        print(f"🔍 Description contains h3: {'<h3>' in description}", flush=True)
        
        # Don't set options for NEW products - let Price Bandit handle the full variant structure
        # Setting options without variants causes Shopify API errors
        if method == "POST":
            # Just create the product with a single basic variant
            # Price Bandit will handle the options and variants
            pass
        
        # For existing products, only update product-level fields to avoid variant/option conflicts
        # Price Bandit will handle variants in Step 4
        if method == "PUT":
            # Remove variants and options from payload - Shopify API doesn't allow clearing options
            # We'll only update product-level fields here, let Price Bandit handle variants later
            print("ℹ️ Updating product-level fields only for existing product (Price Bandit will handle variants)")
            payload["product"].pop("variants", None)
            # Don't send options field either
        
        print(f"🔄 Step 1: {'Updating' if existing_product_id else 'Creating'} product: {product_data.get('title', 'Untitled')}")

        if method == "PUT":
            response = requests.put(url, headers=headers, json=payload)
        else:
            response = requests.post(url, headers=headers, json=payload)
        
        if response.status_code in [200, 201]:
            result = response.json()
            product = result.get("product", {})
            product_id = product.get("id")
            
            action = "updated" if existing_product_id else "created"
            print(f"✅ Step 1 Complete: Product {action} successfully!")
            print(f"🆔 Product ID: {product_id}")
            print(f"📝 Title: {product.get('title')}")
            print(f"🔗 Handle: {product.get('handle')}")
            print(f"🏷️ Tags: {tags}")
            
            # Step 2: Upload media files (images/videos) to the product FIRST
            media_files = product_data.get("media_files", [])
            shopify_media_ids = product_data.get("shopify_media_ids", [])
            total_media = len(media_files) + len(shopify_media_ids)
            
            
            
            if product_id:
                has_new_media = len(media_files) > 0
                is_updating = existing_product_id is not None
                
                # Determine SKU for filenames (needed for both creating and updating)
                def _extract_custom_sku_from_payload(data):
                    try:
                        mfs = data.get("metafields", []) or []
                        for mf in mfs:
                            if mf.get("namespace") == "custom" and mf.get("key") == "sku":
                                val = mf.get("value", "")
                                if isinstance(val, str) and val:
                                    # Handle JSON array string like ["ABC"]
                                    v = val.strip()
                                    if (v.startswith("[") and v.endswith("]")):
                                        try:
                                            parsed = json.loads(v)
                                            if isinstance(parsed, list) and parsed:
                                                return str(parsed[0])
                                        except Exception:
                                            return v
                                    return v
                                return str(val)
                    except Exception:
                        return ""
                    return ""

                payload_custom_sku = _extract_custom_sku_from_payload(product_data)
                provided_sku = product_data.get("sku") or ""

                fetched_custom_sku = ""
                if not payload_custom_sku and not provided_sku:
                    try:
                        # Fetch metafield custom.sku from API for the newly created product
                        url_mf = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/products/{product_id}/metafields.json"
                        headers_mf = {"X-Shopify-Access-Token": ACCESS_TOKEN}
                        r_mf = requests.get(url_mf, headers=headers_mf)
                        if r_mf.status_code == 200:
                            mfs = r_mf.json().get("metafields", [])
                            for mf in mfs:
                                if mf.get("namespace") == "custom" and mf.get("key") == "sku":
                                    fetched_custom_sku = str(mf.get("value", "")).strip()
                                    if fetched_custom_sku:
                                        break
                    except Exception:
                        fetched_custom_sku = ""

                created_variants = result.get("product", {}).get("variants", [])
                created_sku = (created_variants[0].get("sku") if created_variants and created_variants[0].get("sku") else "")
                sku_for_filename = payload_custom_sku or provided_sku or fetched_custom_sku or created_sku or "NOSKU"
                
                # Now handle media based on whether we're updating or creating
                if is_updating:
                    print(f"🔄 Step 2: Managing media for existing product - {len(media_files)} new files, {len(shopify_media_ids)} existing files to keep...")
                    
                    # Step 2a: Remove media not in the keep list
                    # Always call this - empty list means remove all images
                    print(f"🗑️ Step 2a: Removing unwanted media from product (keeping {len(shopify_media_ids) if shopify_media_ids else 0} images)...")
                    manage_results = manage_product_media(product_id, shopify_media_ids or [])
                    if manage_results["success"]:
                        print(f"✅ Step 2a Complete: Removed {manage_results['removed_count']} unwanted media items")
                    else:
                        print(f"⚠️ Step 2a Partial: Some media removal failed: {manage_results['errors']}")
                    
                    # Step 2b: Upload ONLY new media files (don't try to re-attach existing ones)
                    if has_new_media:
                        product_title = product_data.get("title", "")
                        print(f"📤 Step 2b: Uploading {len(media_files)} new media files...")
                        
                        # When updating, only upload new files (don't pass shopify_media_ids to avoid re-attachment attempts)
                        media_results = upload_media_to_product(
                            product_id,
                            media_files,
                            None,  # Don't try to re-attach existing media
                            product_title,
                            product_sku=sku_for_filename
                        )
                        if media_results["success"]:
                            print(f"✅ Step 2b Complete: New media files uploaded successfully!")
                        else:
                            print(f"⚠️ Step 2b Partial: Some media files failed to upload: {media_results['errors']}")
                    
                    # Step 2c: Reorder all media according to media_order
                    # Add a small delay to ensure Shopify has processed the uploads
                    import time
                    if has_new_media:
                        print("⏳ Waiting 2 seconds for Shopify to process new uploads...")
                        time.sleep(2)
                    
                    media_order = product_data.get("media_order", [])
                    if media_order:
                        print(f"🔄 Step 2c: Reordering media according to media_order ({len(media_order)} items)...")
                        reorder_results = reorder_product_media_by_order(product_id, media_order, shopify_media_ids)
                        if reorder_results["success"]:
                            print(f"✅ Step 2c Complete: Media reordered successfully!")
                        else:
                            print(f"⚠️ Step 2c Partial: Some media reordering failed: {reorder_results['errors']}")
                    elif shopify_media_ids:
                        # Fallback to old method if no media_order provided
                        print(f"🔄 Step 2c: Reordering {len(shopify_media_ids)} existing media items (fallback method)...")
                        reorder_results = reorder_product_media(product_id, shopify_media_ids)
                        if reorder_results["success"]:
                            print(f"✅ Step 2c Complete: Media reordered successfully!")
                        else:
                            print(f"⚠️ Step 2c Partial: Some media reordering failed: {reorder_results['errors']}")
                    
                    print(f"✅ Step 2 Complete: Media management finished for existing product!")
                
                elif has_new_media or total_media > 0:
                    # Creating new product - upload all media
                    print(f"🔄 Step 2: Uploading {len(media_files)} new files and attaching {len(shopify_media_ids)} existing files for new product...")
                    product_title = product_data.get("title", "")
                    
                    media_results = upload_media_to_product(
                        product_id,
                        media_files,
                        shopify_media_ids,
                        product_title,
                        product_sku=sku_for_filename
                    )
                    if media_results["success"]:
                        print(f"✅ Step 2 Complete: All media files processed successfully!")
                    else:
                        print(f"⚠️ Step 2 Partial: Some media files failed to process: {media_results['errors']}")
                else:
                    print(f"⏭️ Step 2 Skipped: No media to manage")
            
            # Step 3: Create metafields if provided
            metafields = product_data.get("metafields", [])
            
            # Add category and subcategory metafields if provided
            if product_data.get("category"):
                metafields.append({
                    "namespace": "custom",
                    "key": "custom_category",
                    "value": f'["{product_data["category"]}"]',  # Format as JSON array for list type
                    "type": "list.single_line_text_field"
                })

            if product_data.get("subcategory"):
                # Determine which metafield key to use based on subcategory index
                try:
                    from scripts.product_creator.categories import get_subcategory_metafield_key
                    metafield_key = get_subcategory_metafield_key(product_data["subcategory"])
                except (ImportError, AttributeError):
                    # Fallback to default if helper function not available
                    metafield_key = "subcategory"
                
                metafields.append({
                    "namespace": "custom",
                    "key": metafield_key,
                    "value": f'["{product_data["subcategory"]}"]',  # Format as JSON array for list type
                    "type": "list.single_line_text_field"
                })
            
            # Add colour options metafield if provided
            product_colours = product_data.get("product_colours", "").strip()
            if product_colours:
                print(f"🎨 Colours provided: {product_colours}", flush=True)
                metafields.append({
                    "namespace": "custom",
                    "key": "product_colours",
                    "value": product_colours,  # Store comma-separated colours
                    "type": "single_line_text_field"
                })
                
                # Create default pricing metafields for colour variants if they don't exist
                # This allows Price Bandit to create colour variants even without explicit pricing
                has_trade_pricing = any(mf.get("key") == "pricejsontr" for mf in metafields)
                has_endc_pricing = any(mf.get("key") == "pricejsoner" for mf in metafields)
                
                if not has_trade_pricing:
                    print(f"➕ Adding default trade pricing for colour variants", flush=True)
                    metafields.append({
                        "namespace": "custom",
                        "key": "pricejsontr",
                        "value": '[{"min": 0, "max": 100, "price": 0.00}]',  # Default pricing band
                        "type": "single_line_text_field"
                    })
                
                if not has_endc_pricing:
                    print(f"➕ Adding default end customer pricing for colour variants", flush=True)
                    metafields.append({
                        "namespace": "custom",
                        "key": "pricejsoner", 
                        "value": '[{"min": 0, "max": 100, "price": 0.00}]',  # Default pricing band
                        "type": "single_line_text_field"
                    })
            
            if metafields and product_id:
                print(f"🔄 Step 3: Creating {len(metafields)} metafields...")
                metafield_results = create_metafields(product_id, metafields)
                if metafield_results["success"]:
                    print(f"✅ Step 3 Complete: All metafields created successfully!")
                    # Small delay to ensure metafields are fully saved before Price Bandit reads them
                    import time
                    time.sleep(0.5)
                else:
                    print(f"⚠️ Step 3 Partial: Some metafields failed to create: {metafield_results['errors']}")
            else:
                print(f"⏭️ Step 3 Skipped: No metafields to create")
            
            # Step 4: Run Price Bandit script to create variants (after media and metafields are created)
            print(f"🔄 Step 4: Running Price Bandit script to create variants...")
            
            # Import Price Bandit functions
            try:
                import sys
                import os
                # Add the scripts directory to the path
                scripts_dir = os.path.join(os.path.dirname(__file__), '..')
                if scripts_dir not in sys.path:
                    sys.path.append(scripts_dir)
                from Price_Bandit import process_product
                
                print(f"🔍 Price Bandit imported successfully")
                
                # Create a product object that Price Bandit expects
                product_for_bandit = {
                    "id": product_id,
                    "title": product.get('title', 'Unknown Product')
                }
                
                # Pass colour_images if provided
                colour_images = product_data.get("colour_images")
                print(f"🔍 Received colour_images from frontend: {colour_images}, type: {type(colour_images)}", flush=True)
                if colour_images:
                    # If it's already a dict from JSON parsing in app.py, use it directly
                    # Otherwise convert from string
                    if isinstance(colour_images, str):
                        import json
                        try:
                            colour_images = json.loads(colour_images)
                            print(f"🔧 Parsed colour_images from string: {colour_images}", flush=True)
                        except Exception as e:
                            print(f"⚠️ Failed to parse colour_images: {e}", flush=True)
                            colour_images = None
                    
                    if colour_images:
                        # Store as a custom attribute to pass to Price Bandit
                        product_for_bandit["_colour_images"] = colour_images
                        print(f"🔍 Storing colour_images in product_for_bandit: {product_for_bandit.get('_colour_images')}", flush=True)
                
                print(f"🔍 Running Price Bandit for product ID: {product_id}")
                
                # Run Price Bandit's process_product function
                price_bandit_success = process_product(product_for_bandit)
                if price_bandit_success:
                    print(f"✅ Step 4 Complete: Price Bandit script executed successfully!")
                else:
                    print(f"❌ Step 4 Failed: Price Bandit script failed to create variants!")
                
            except ImportError as e:
                print(f"❌ Step 4 Failed: Could not import Price Bandit: {str(e)}")
            except Exception as e:
                print(f"❌ Step 4 Failed: Price Bandit execution error: {str(e)}")
                import traceback
                traceback.print_exc()
            
            # Step 5: Update taxable field on variants if needed (Price Bandit sets taxable=True by default)
            if not taxable:  # If user selected "No" for charge VAT
                print(f"🔄 Step 5: Updating taxable field to False on all variants...")
                taxable_updated = update_product_taxable(product_id, False)
                if taxable_updated:
                    print(f"✅ Step 5 Complete: Taxable field updated to False on all variants")
                else:
                    print(f"❌ Step 5 Failed: Could not update taxable field")
            else:
                print(f"✅ Step 5 Complete: Variants created with taxable=True (Price Bandit default)")
            
            print(f"🎉 Product {action} process completed!")
            print(f"🌐 URL: https://{STORE_DOMAIN}/admin/products/{product_id}")

            return {
                "success": True,
                "product": product,
                "message": f"Product '{product.get('title')}' {action} successfully"
            }
        else:
            error_msg = f"Failed to {method.lower()} product: {response.status_code} - {response.text}"
            print(f"❌ {error_msg}")
            return {
                "success": False,
                "error": error_msg
            }
            
    except Exception as e:
        error_msg = f"Error creating product: {str(e)}"
        print(f"💥 {error_msg}")
        return {
            "success": False,
            "error": error_msg
        }

def get_metafield_choices(namespace_key):
    """
    Get preset choices for a specific metafield from the categories file
    
    Args:
        namespace_key (str): The metafield namespace and key (e.g., "custom.custom_category")
    
    Returns:
        list: List of preset choices for the metafield
    """
    try:
        # Import the categories module
        from .categories import get_metafield_choices as get_categories_choices
        
        # Parse namespace and key from the input
        if '.' in namespace_key:
            namespace, key = namespace_key.split('.', 1)
        else:
            namespace = namespace_key
            key = ""
        
        # Get choices from the categories file
        choices = get_categories_choices(key)
        if choices:
            print(f"Found {len(choices)} preset choices for {namespace_key}: {choices}")
            return choices
        else:
            print(f"No preset choices found for {namespace_key}")
            return []
            
    except Exception as e:
        print(f"Error fetching metafield choices for {namespace_key}: {str(e)}")
        return []

def get_existing_metafield_values(namespace, key):
    """Fallback function to get existing metafield values"""
    try:
        graphql_url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/graphql.json"
        headers = {
            'X-Shopify-Access-Token': ACCESS_TOKEN,
            'Content-Type': 'application/json',
        }
        
        query = """
        query getMetafieldValues($namespace: String!) {
            products(first: 250) {
                edges {
                    node {
                        metafields(first: 50, namespace: $namespace) {
                            edges {
                                node {
                                    key
                                    value
                                }
                            }
                        }
                    }
                }
            }
        }
        """
        
        response = requests.post(graphql_url, headers=headers, json={
            'query': query,
            'variables': {"namespace": namespace}
        })
        
        if response.status_code == 200:
            data = response.json()
            products = data.get('data', {}).get('products', {}).get('edges', [])
            
            if products:
                unique_values = set()
                for product_edge in products:
                    product = product_edge['node']
                    metafields = product.get('metafields', {}).get('edges', [])
                    for metafield_edge in metafields:
                        metafield = metafield_edge['node']
                        metafield_key = metafield.get('key', '')
                        if metafield_key == key:
                            value = metafield.get('value', '')
                            if value and value.strip():
                                try:
                                    import json
                                    parsed_value = json.loads(value.strip())
                                    if isinstance(parsed_value, list) and len(parsed_value) > 0:
                                        unique_values.add(parsed_value[0])
                                    else:
                                        unique_values.add(value.strip())
                                except (json.JSONDecodeError, IndexError):
                                    unique_values.add(value.strip())
                
                choices = sorted(list(unique_values))
                print(f"Fallback: Found {len(choices)} existing values for {namespace}.{key}: {choices}")
                return choices
        
        return []
    except Exception as e:
        print(f"Error in fallback function: {str(e)}")
        return []

def get_product_templates():
    """
    Get predefined product templates for common product types
    
    Returns:
        dict: Available product templates
    """
    templates = {
        "simple_product": {
            "name": "Simple Product",
            "description": "A basic product with one variant",
            "template": {
                "title": "New Product",
                "description": "Product description",
                "vendor": "",
                "product_type": "",
                "tags": "",
                "status": "draft",
                "price": "0.00",
                "sku": "",
                "inventory_quantity": 0,
                "variants": []
            }
        },
        "size_variants": {
            "name": "Product with Size Variants",
            "description": "Product with different sizes (S, M, L, XL)",
            "template": {
                "title": "New Product with Sizes",
                "description": "Product description",
                "vendor": "",
                "product_type": "",
                "tags": "",
                "status": "draft",
                "options": [
                    {
                        "name": "Size",
                        "values": ["S", "M", "L", "XL"]
                    }
                ],
                "variants": [
                    {"option1": "S", "price": "0.00", "sku": "", "inventory_quantity": 0},
                    {"option1": "M", "price": "0.00", "sku": "", "inventory_quantity": 0},
                    {"option1": "L", "price": "0.00", "sku": "", "inventory_quantity": 0},
                    {"option1": "XL", "price": "0.00", "sku": "", "inventory_quantity": 0}
                ]
            }
        },
        "color_size_variants": {
            "name": "Product with Color & Size",
            "description": "Product with color and size variants",
            "template": {
                "title": "New Product with Colors & Sizes",
                "description": "Product description",
                "vendor": "",
                "product_type": "",
                "tags": "",
                "status": "draft",
                "options": [
                    {
                        "name": "Color",
                        "values": ["Red", "Blue", "Green"]
                    },
                    {
                        "name": "Size",
                        "values": ["S", "M", "L"]
                    }
                ],
                "variants": [
                    {"option1": "Red", "option2": "S", "price": "0.00", "sku": "", "inventory_quantity": 0},
                    {"option1": "Red", "option2": "M", "price": "0.00", "sku": "", "inventory_quantity": 0},
                    {"option1": "Red", "option2": "L", "price": "0.00", "sku": "", "inventory_quantity": 0},
                    {"option1": "Blue", "option2": "S", "price": "0.00", "sku": "", "inventory_quantity": 0},
                    {"option1": "Blue", "option2": "M", "price": "0.00", "sku": "", "inventory_quantity": 0},
                    {"option1": "Blue", "option2": "L", "price": "0.00", "sku": "", "inventory_quantity": 0},
                    {"option1": "Green", "option2": "S", "price": "0.00", "sku": "", "inventory_quantity": 0},
                    {"option1": "Green", "option2": "M", "price": "0.00", "sku": "", "inventory_quantity": 0},
                    {"option1": "Green", "option2": "L", "price": "0.00", "sku": "", "inventory_quantity": 0}
                ]
            }
        }
    }
    
    return templates

def validate_product_data(product_data):
    """
    Validate product data before creation
    
    Args:
        product_data (dict): Product information to validate
    
    Returns:
        dict: Validation result with success status and any errors
    """
    errors = []
    
    # Required fields
    if not product_data.get("title", "").strip():
        errors.append("Product title is required")
    
    return {
        "valid": len(errors) == 0,
        "errors": errors
    }


def main():
    """
    Main function for command line usage
    """
    print("🛍️  Product Editor/Creator - Shopify Product Tool")
    print("=" * 50)
    
    # Example usage
    if len(sys.argv) > 1:
        if sys.argv[1] == "--templates":
            templates = get_product_templates()
            print("\n📋 Available Product Templates:")
            for key, template in templates.items():
                print(f"\n🔹 {template['name']}")
                print(f"   {template['description']}")
            return
    
    # Interactive mode
    print("\n📝 Enter product details:")
    
    product_data = {
        "title": input("Product Title: ").strip(),
        "description": input("Description (optional): ").strip(),
        "vendor": input("Vendor (optional): ").strip(),
        "product_type": input("Product Type (optional): ").strip(),
        "tags": input("Tags (comma-separated, optional): ").strip(),
        "status": input("Status (draft/active, default: draft): ").strip() or "draft",
        "price": input("Price (default: 0.00): ").strip() or "0.00",
        "sku": input("SKU (optional): ").strip(),
        "inventory_quantity": input("Inventory Quantity (default: 0): ").strip() or "0"
    }
    
    # Validate the data
    validation = validate_product_data(product_data)
    if not validation["valid"]:
        print("\n❌ Validation Errors:")
        for error in validation["errors"]:
            print(f"   • {error}")
        return
    
    # Create the product
    result = create_product(product_data)
    
    if result["success"]:
        print(f"\n✅ {result['message']}")
    else:
        print(f"\n❌ {result['error']}")

if __name__ == "__main__":
    main()
