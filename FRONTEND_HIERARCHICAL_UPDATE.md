# Frontend Hierarchical Knowledgebase Update Guide

## Overview
The backend now returns websites in hierarchical tree structure with parent-child relationships. This guide shows how to update the frontend to display websites as expandable trees instead of flat lists.

## API Changes

### New Response Structure
The `/api/v1/knowledgebase/files` endpoint now returns:

```json
{
  "success": true,
  "files": [...],           // Flat list of uploaded files (unchanged)
  "websites": [            // NEW: Hierarchical website tree
    {
      "id": "123",
      "display_name": "Example.com",
      "file_type": "WEBSITE",
      "url": "https://example.com",
      "domain": "example.com", 
      "title": "Example Site",
      "description": "Site description",
      "pages_scraped": 5,
      "depth": 0,
      "parent_id": null,
      "children": [         // Child pages
        {
          "id": "124",
          "display_name": "About Us",
          "file_type": "WEBSITE",
          "url": "https://example.com/about",
          "depth": 1,
          "parent_id": "123",
          "children": [],
          "is_expanded": false
        }
      ],
      "is_expanded": false    // UI state control
    }
  ],
  "summary": {
    "uploaded_files": 5,
    "scraped_websites": 3,
    "total_pages": 12
  }
}
```

## Frontend Implementation Guide

### 1. Update API Response Handling
```javascript
// Before: Only handled files array
const files = response.files;

// After: Handle both files and websites
const files = response.files || [];
const websites = response.websites || [];
const summary = response.summary || {};
```

### 2. Create Hierarchical Tree Component
```jsx
// WebsiteTreeItem.jsx
const WebsiteTreeItem = ({ website, level = 0, onToggle }) => {
  const hasChildren = website.children && website.children.length > 0;
  const indent = { paddingLeft: `${level * 20}px` };
  
  return (
    <div style={indent}>
      <div className="website-item">
        {/* Expand/Collapse Button */}
        {hasChildren && (
          <button 
            onClick={() => onToggle(website.id)}
            className="expand-button"
          >
            {website.is_expanded ? '−' : '+'}
          </button>
        )}
        
        {/* Website Info */}
        <div className="website-info">
          <span className="website-title">{website.display_name}</span>
          <span className="website-url">{website.url}</span>
          <span className="website-type">{website.file_type}</span>
        </div>
        
        {/* Child Pages */}
        {hasChildren && website.is_expanded && (
          <div className="children">
            {website.children.map(child => (
              <WebsiteTreeItem 
                key={child.id} 
                website={child} 
                level={level + 1}
                onToggle={onToggle}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
```

### 3. Update Main Knowledgebase Component
```jsx
// Knowledgebase.jsx
const Knowledgebase = () => {
  const [data, setData] = useState({ files: [], websites: [] });
  const [expandedIds, setExpandedIds] = useState(new Set());
  
  useEffect(() => {
    fetch('/api/v1/knowledgebase/files')
      .then(res => res.json())
      .then(setData);
  }, []);
  
  const handleToggle = (websiteId) => {
    setExpandedIds(prev => {
      const newSet = new Set(prev);
      if (newSet.has(websiteId)) {
        newSet.delete(websiteId);
      } else {
        newSet.add(websiteId);
      }
      return newSet;
    });
    
    // Update expanded state in data
    setData(prev => ({
      ...prev,
      websites: updateExpandedState(prev.websites, websiteId, expandedIds)
    }));
  };
  
  // Helper to update expanded state
  const updateExpandedState = (websites, websiteId, expandedIds) => {
    return websites.map(website => {
      if (website.id === websiteId) {
        return { ...website, is_expanded: !expandedIds.has(websiteId) };
      }
      if (website.children) {
        return {
          ...website,
          children: updateExpandedState(website.children, websiteId, expandedIds)
        };
      }
      return website;
    });
  };
  
  return (
    <div className="knowledgebase">
      {/* Summary Section */}
      <div className="summary">
        <h2>Knowledgebase Summary</h2>
        <div className="summary-stats">
          <div>Uploaded Files: {data.summary.uploaded_files}</div>
          <div>Websites: {data.summary.scraped_websites}</div>
          <div>Total Pages: {data.summary.total_pages}</div>
        </div>
      </div>
      
      {/* Files Section */}
      <div className="files-section">
        <h2>Uploaded Files</h2>
        <FileList files={data.files} />
      </div>
      
      {/* Websites Section */}
      <div className="websites-section">
        <h2>Scraped Websites</h2>
        <div className="website-tree">
          {data.websites.map(website => (
            <WebsiteTreeItem 
              key={website.id}
              website={website}
              onToggle={handleToggle}
            />
          ))}
        </div>
      </div>
    </div>
  );
};
```

### 4. CSS Styling
```css
.knowledgebase {
  padding: 20px;
  font-family: Arial, sans-serif;
}

.summary {
  background: #f5f5f5;
  padding: 15px;
  border-radius: 8px;
  margin-bottom: 20px;
}

.summary-stats {
  display: flex;
  gap: 20px;
}

.files-section, .websites-section {
  margin-bottom: 30px;
}

.website-item {
  display: flex;
  align-items: center;
  padding: 8px 0;
  border-bottom: 1px solid #eee;
}

.expand-button {
  width: 24px;
  height: 24px;
  border: 1px solid #ccc;
  background: #f9f9f9;
  border-radius: 4px;
  cursor: pointer;
  margin-right: 10px;
  font-weight: bold;
}

.expand-button:hover {
  background: #e9e9e9;
}

.website-info {
  display: flex;
  flex-direction: column;
  flex: 1;
}

.website-title {
  font-weight: bold;
  color: #333;
}

.website-url {
  color: #666;
  font-size: 0.9em;
  margin-top: 2px;
}

.website-type {
  background: #e3f2fd;
  color: white;
  padding: 2px 6px;
  border-radius: 12px;
  font-size: 0.8em;
  margin-left: 10px;
}

.children {
  border-left: 2px solid #ddd;
  margin-left: 12px;
}
```

## Key Features

### ✅ What This Enables
- **Hierarchical Display**: Parent pages with expand/collapse for children
- **Visual Hierarchy**: Clear parent-child relationships with indentation
- **Interactive UI**: +/- buttons to expand/collapse sections
- **State Management**: Track which nodes are expanded
- **Summary Stats**: Overview of knowledgebase contents
- **Backward Compatible**: Existing file uploads still work the same

### 🔄 Migration Steps
1. **Update API Handling**: Access `websites` array from response
2. **Create Tree Component**: Reusable component for hierarchical display
3. **Add State Management**: Track expanded/collapsed states
4. **Style Hierarchy**: Visual indentation and expand buttons
5. **Test Functionality**: Verify expand/collapse works correctly

## Alternative: Use New /knowledgebase Endpoint

If you prefer to use the dedicated endpoint instead:
```javascript
// Alternative: Use dedicated hierarchical endpoint
const response = await fetch('/api/v1/knowledgebase/knowledgebase');
const { files, websites, summary } = await response.json();
```

## Notes

- **No Backend Changes Required**: Frontend can use existing `/files` endpoint
- **Gradual Migration**: Can update UI incrementally
- **Performance**: Tree structure is efficient for large datasets
- **Scalability**: Supports unlimited nesting levels
- **Responsive**: CSS can be adapted for mobile

## Testing

Test with these scenarios:
1. **Root Pages**: Should show expand button if they have children
2. **Child Pages**: Should be indented under parent
3. **Expand/Collapse**: Toggle should show/hide children correctly
4. **Multiple Levels**: Test deep nesting (grandchildren, etc.)
5. **Empty State**: Handle when no websites exist
6. **Mixed Content**: Verify files and websites display together
