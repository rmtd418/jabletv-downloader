import os

def deleteMp4(folderPath, keep_file=None):
    """清理临时 .mp4 片段，保留最终文件 keep_file"""
    files = os.listdir(folderPath)
    for file in files:
        if keep_file and file == keep_file:
            continue
        if file.endswith('.mp4'):
            try:
                os.remove(os.path.join(folderPath, file))
            except (PermissionError, OSError):
                pass  # 被佔用就跳過，不阻斷流程


def deleteM3u8(folderPath):
    files = os.listdir(folderPath)
    for file in files:
        if file.endswith('.m3u8'):
            try:
                os.remove(os.path.join(folderPath, file))
            except (PermissionError, OSError):
                pass
