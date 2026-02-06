import os
import re

def process_dao_file(file_path, service_name):
    with open(file_path, 'r') as f:
        content = f.read()

    # 1. Update imports
    if 'from shared.otel_logger import get_otel_logger' in content:
         pass # Already good because of redirect, but better to be explicit if we want
    
    # Ensure get_otel_logger is used
    if 'get_otel_logger' not in content:
        content = content.replace('import logging', 'import logging\nfrom shared.otel_logger import get_otel_logger')
        # find where classes are defined and put logger above
        content = re.sub(r'(class \w+DAO:)', r'logger = get_otel_logger("\1".lower().replace("class ", "").replace(":", ""), "' + service_name + r'")\n\n\1', content)

    # 2. Find DB executions and add log_db_operation before
    # Common patterns:
    # result = await conn.fetchval(query, ...)
    # result = await conn.fetchrow(query, ...)
    # results = await conn.fetch(query, ...)
    # result = await conn.execute(query, ...)

    exec_patterns = [
        r'(\s+)(result\s*=\s*await\s+conn\.fetchval\((query[^)]*)\))',
        r'(\s+)(result\s*=\s*await\s+conn\.fetchrow\((query[^)]*)\))',
        r'(\s+)(results\s*=\s*await\s+conn\.fetch\((query[^)]*)\))',
        r'(\s+)(rows\s*=\s*await\s+conn\.fetch\((query[^)]*)\))',
        r'(\s+)(result\s*=\s*await\s+conn\.execute\((query[^)]*)\))',
        r'(\s+)(records\s*=\s*await\s+conn\.fetch\((query[^)]*)\))'
    ]

    for pattern in exec_patterns:
        content = re.sub(pattern, r'\1logger.log_db_operation(\3)\1\2', content)

    # 3. Handle cases where query is a string literal (though rare in these DAOs)
    
    # 4. Update log_db_query calls to include params if they are missing
    # (Existing log_db_query calls already exist in some DAOs)

    with open(file_path, 'w') as f:
        f.write(content)

# This script is a bit simplified. I'll do it more carefully.
