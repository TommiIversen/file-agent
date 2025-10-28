from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field, field_serializer


class DirectoryItem(BaseModel):
    """Represents a file or directory with metadata."""

    name: str = Field(..., description="File or directory name")
    path: str = Field(..., description="Full path to the item")
    is_directory: bool = Field(..., description="True if item is a directory")
    is_hidden: bool = Field(default=False, description="True if item is hidden")
    size_bytes: Optional[int] = Field(
        None, description="File size in bytes (None for directories)"
    )
    created_time: Optional[datetime] = Field(None, description="Creation time")
    modified_time: Optional[datetime] = Field(
        None, description="Last modification time"
    )

    # Hierarchy fields for tree view
    parent_path: Optional[str] = Field(None, description="Parent directory path")
    depth_level: int = Field(
        default=0, description="Depth level in directory tree (0 = root)"
    )
    relative_path: str = Field(default="", description="Relative path from scan root")

    # Nested structure for true tree representation
    children: Optional[List["DirectoryItem"]] = Field(
        default=None, description="Child items (for directories)"
    )

    @field_serializer('created_time', 'modified_time', when_used='json')
    def serialize_datetime(self, value: Optional[datetime]) -> Optional[str]:
        """Serialize datetime fields to ISO format for JSON output."""
        return value.isoformat() if value else None


class DirectoryScanResult(BaseModel):
    """Result of a directory scan operation."""

    path: str = Field(..., description="Scanned directory path")
    is_accessible: bool = Field(..., description="Whether directory was accessible")
    items: List[DirectoryItem] = Field(
        default_factory=list, description="Found files and directories (flat list)"
    )
    tree: List[DirectoryItem] = Field(
        default_factory=list, description="Found items as nested tree structure"
    )
    total_items: int = Field(default=0, description="Total number of items found")
    total_files: int = Field(default=0, description="Number of files found")
    total_directories: int = Field(default=0, description="Number of directories found")
    scan_duration_seconds: float = Field(default=0.0, description="Time taken to scan")
    error_message: Optional[str] = Field(
        None, description="Error message if scan failed"
    )

    def __init__(self, **data):
        super().__init__(**data)
        # Auto-calculate totals from items
        if self.items:
            self.total_items = len(self.items)
            self.total_files = sum(1 for item in self.items if not item.is_directory)
            self.total_directories = sum(1 for item in self.items if item.is_directory)

        # Build tree structure from flat items list
        if self.items and not self.tree:
            self.tree = self._build_tree_structure()

    def _build_tree_structure(self) -> List[DirectoryItem]:
        """Build nested tree structure from flat items list."""
        if not self.items:
            return []

        # Group items by parent path
        items_by_parent = {}
        root_items = []

        for item in self.items:
            if item.depth_level == 0:
                # Root level items
                root_items.append(item)
            else:
                # Group by parent path
                parent = item.parent_path or ""
                if parent not in items_by_parent:
                    items_by_parent[parent] = []
                items_by_parent[parent].append(item)

        # Recursively build tree
        def add_children(item: DirectoryItem) -> DirectoryItem:
            if item.is_directory and item.path in items_by_parent:
                # Create new item with children
                item_copy = item.model_copy()
                item_copy.children = []
                for child in items_by_parent[item.path]:
                    item_copy.children.append(add_children(child))
                return item_copy
            else:
                # Leaf node - no children
                item_copy = item.model_copy()
                item_copy.children = None if not item.is_directory else []
                return item_copy

        # Build tree from root items
        tree = []
        for root_item in root_items:
            tree.append(add_children(root_item))

        return tree

