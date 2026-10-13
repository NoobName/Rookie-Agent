import hashlib

from .policy import inside


def read_file(root, validated):
    result = {}
    import codecs

    p = inside(root, validated["path"])
    digest = hashlib.sha256()
    with p.open("rb") as handle:
        size = 0
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
        handle.seek(0)
        head = handle.read(4096)
        handle.seek(validated["offset"])
        raw = handle.read(validated["max_bytes"])
    result.update(sha256=digest.hexdigest(), size_bytes=size, offset=validated["offset"])
    if b"\0" in head or p.suffix.lower() in (
        ".exe",
        ".dll",
        ".bmp",
        ".png",
        ".jpg",
        ".jpeg",
        ".pdf",
        ".zip",
        ".docx",
        ".xlsx",
    ):
        result.update(
            output="二进制文件：已返回大小和哈希。不能作为 UTF-8 源码读取；请使用对应文档/图像工具，或终端验证文件格式。",
            binary=True,
            truncated=False,
        )
    else:
        decoder = codecs.getincrementaldecoder("utf-8")()
        try:
            text = decoder.decode(raw, final=validated["offset"] + len(raw) >= size)
            next_offset = validated["offset"] + len(raw) - len(decoder.getstate()[0])
            result.update(
                output=text,
                binary=False,
                truncated=next_offset < size,
                next_offset=next_offset if next_offset < size else None,
            )
        except UnicodeDecodeError:
            result.update(
                output="文件不是有效 UTF-8 文本，或 offset 不在字符边界。请用上次返回的 next_offset，或通过终端按实际编码读取。",
                binary=True,
                truncated=False,
            )
    return result
