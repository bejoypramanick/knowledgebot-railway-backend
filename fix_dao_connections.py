#!/usr/bin/env python3
"""
Script to update all DAOs to manage their own database connections
"""

import os
import re

def update_dao_file(file_path):
    """Update a single DAO file to manage its own database connections"""
    with open(file_path, 'r') as f:
        content = f.read()
    
    # Add shared.db import if not present
    if 'from shared.db import get_db_connection' not in content:
        # Find the imports section and add the import
        import_pattern = r'(import logging\n)'
        replacement = r'\1from shared.db import get_db_connection\n'
        content = re.sub(import_pattern, replacement, content)
    
    # Update constructor to remove connection parameter
    constructor_pattern = r'def __init__\(self, connection.*?\):'
    constructor_replacement = 'def __init__(self):\n        pass  # No connection parameter - DAO manages its own connection'
    content = re.sub(constructor_pattern, constructor_replacement, content, flags=re.DOTALL)
    
    # Replace self.conn with async with get_db_connection() as conn:
    # This is more complex, so we'll do a simpler approach
    
    # Remove self.conn = connection line if exists
    content = re.sub(r'self\.conn = connection\n', '', content)
    
    # Replace self.conn with conn in async methods
    # This is a simplified approach - in practice, each method needs to be wrapped
    method_pattern = r'(\s+)(async def \w+\(.*?\).*?:\n)(.*?)(?=\n    async def|\n\n|\Z)'
    
    def wrap_method(match):
        indent = match.group(1)
        method_def = match.group(2)
        method_body = match.group(3)
        
        # If method already has get_db_connection, skip it
        if 'get_db_connection' in method_body:
            return match.group(0)
        
        # Replace self.conn with conn and wrap in async with
        method_body = method_body.replace('self.conn', 'conn')
        
        # Indent the method body
        lines = method_body.split('\n')
        indented_lines = []
        for line in lines:
            if line.strip():  # Skip empty lines
                indented_lines.append('    ' + line)
            else:
                indented_lines.append(line)
        
        wrapped_body = f'        async with get_db_connection() as conn:\n' + '\n'.join(indented_lines)
        
        return f'{indent}{method_def}{wrapped_body}\n'
    
    # Apply the transformation
    content = re.sub(method_pattern, wrap_method, content, flags=re.DOTALL)
    
    with open(file_path, 'w') as f:
        f.write(content)
    
    print(f"Updated: {file_path}")

def main():
    """Main function to update all DAO files"""
    dao_files = [
        './configuration/dao/chat_log_dao.py',
        './configuration/dao/feedback_dao.py', 
        './configuration/dao/user_dao.py',
        './configuration/dao/widget_dao.py',
        './configuration/dao/chatbot_dao.py',
        './configuration/dao/performance_dao.py',
        './website_crawling/dao/scraping_dao.py',
        './chatbot_orchestration/dao/chat_dao.py',
        './knowledgebase_ingestion/dao/file_dao.py'
    ]
    
    for dao_file in dao_files:
        if os.path.exists(dao_file):
            update_dao_file(dao_file)
        else:
            print(f"File not found: {dao_file}")

if __name__ == "__main__":
    main()
