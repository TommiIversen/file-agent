# Network Copy Optimization

## Overview
The File Transfer Agent uses a simple, optimal chunk size strategy for network file transfers, providing excellent performance with minimal complexity.

## Simple Chunk Size Strategy

### Optimal for All Files
The system uses a single, proven chunk size that works excellently across all file sizes:

- **All files**: 2MB chunks (optimal balance)
- **Growing files**: 2MB chunks (same as normal files)
- **Network efficiency**: Excellent for all file sizes from small to very large

### Why 2MB Works Best
- **Small files**: Still efficient, minimal overhead
- **Large files**: Optimal network throughput
- **Network transfers**: Perfect balance of memory usage and efficiency
- **Simple**: No complex logic, easy to understand and maintain

## Configuration

```env
# Simple, optimal chunk size for all file transfers
CHUNK_SIZE_KB=2048   # 2MB chunks - optimal for network transfers
GROWING_FILE_CHUNK_SIZE_KB=2048  # 2MB for growing files
```

## Performance Benefits

### Before Optimization
- **Normal files**: 1MB chunks
- **Large files**: 2MB chunks with complex threshold logic
- **Code complexity**: Artificial distinction between file sizes

### After Simplification  
- **All files**: 2MB chunks (simple and optimal)
- **Growing files**: 2MB chunks (consistent)
- **Code complexity**: Minimal - one chunk size setting
- **Performance**: Excellent across all file sizes

## Implementation Details

The chunk size selection is now trivial:

```python
# Simple and effective:
chunk_size = settings.chunk_size_kb * 1024  # 2MB for all files
```

This optimization eliminates unnecessary complexity while providing optimal performance for the intended use case of copying various sized video files over network to NAS storage.