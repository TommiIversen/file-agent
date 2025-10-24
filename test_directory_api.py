import asyncio
import json
from app.services.directory_scanner import DirectoryScannerService
from app.config import Settings

async def test_api():
    settings = Settings()
    scanner = DirectoryScannerService(settings)
    
    result = await scanner.scan_source_directory(recursive=True, max_depth=2)
    
    # Convert to dict for better viewing
    data = result.model_dump()
    
    print('=== SAMPLE OF SCAN RESULT ===')
    print(f'Path: {data["path"]}')
    print(f'Accessible: {data["is_accessible"]}')
    print(f'Total items: {data["total_items"]}')
    print(f'Tree items: {len(data["tree"])}')
    
    print('\n=== FIRST FEW FLAT ITEMS ===')
    for i, item in enumerate(data['items'][:3]):
        print(f'{i+1}. {item["name"]} -> Directory: {item["is_directory"]}')
    
    print('\n=== TREE STRUCTURE (first level) ===')
    for i, item in enumerate(data['tree'][:3]):
        children = item.get('children', [])
        children_count = len(children) if children is not None else 0
        print(f'{i+1}. {item["name"]} -> Directory: {item["is_directory"]}, Children: {children_count}')

if __name__ == "__main__":
    asyncio.run(test_api())