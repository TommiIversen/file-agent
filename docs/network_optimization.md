# Network Copy Optimization

## Overview
The File Transfer Agent has been optimized for network file transfers with dynamic chunk sizing based on file characteristics.

## Chunk Size Strategy

### Normal Files (< 1GB)
- **Chunk Size**: 1MB (1024KB)
- **Use Case**: Standard video files, documents, smaller media files
- **Rationale**: 1MB provides good network efficiency without excessive memory usage

### Large Files (≥ 1GB)  
- **Chunk Size**: 2MB (2048KB)
- **Use Case**: Large video files (typical 25GB MXF files)
- **Rationale**: Larger chunks reduce network overhead for big file transfers

### Growing Files
- **Chunk Size**: 2MB (2048KB) 
- **Use Case**: Files being written while copying (live streams at ~50Mbit)
- **Rationale**: Larger chunks handle streaming data efficiently with safety margin

## Configuration

```env
# Chunk sizes for network copy optimization
NORMAL_FILE_CHUNK_SIZE_KB=1024      # 1MB for normal files
LARGE_FILE_CHUNK_SIZE_KB=2048       # 2MB for large files  
LARGE_FILE_THRESHOLD_GB=1.0         # Files ≥1GB use large chunks
GROWING_FILE_CHUNK_SIZE_KB=2048     # 2MB for growing files
```

## Performance Benefits

### Before Optimization
- **All files**: 64KB chunks
- **Network overhead**: High for large files
- **Transfer efficiency**: Poor for 25GB files over network

### After Optimization  
- **Small files**: 1MB chunks (16x improvement)
- **Large files**: 2MB chunks (32x improvement)  
- **Growing files**: 2MB chunks optimized for streaming
- **Network efficiency**: Significantly improved for network transfers

## Implementation Details

The chunk size selection is automatic based on file size:

```python
# FileCopyExecutor and CopyStrategyFactory automatically select:
if file_size >= 1GB:
    use 2MB chunks  # Optimal for large network transfers
else:
    use 1MB chunks  # Good balance for smaller files
```

This optimization is particularly important for the intended use case of copying large video files over network to NAS storage.