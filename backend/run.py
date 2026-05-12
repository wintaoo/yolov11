import os
import sys
import logging

# 添加项目根目录到 Python 路径
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
sys.path.insert(0, project_root)

from backend.app import create_app

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

PORT_FILE = os.path.join(current_dir, '.port')
DEFAULT_PORT = int(os.environ.get('PORT', 5050))
PORT_RANGE = 10  # 从默认端口开始尝试 10 个端口


def write_port_file(port):
    with open(PORT_FILE, 'w') as f:
        f.write(str(port))
    logger.info(f"端口已写入 {PORT_FILE}: {port}")


def try_start_app(app, start_port):
    """尝试在指定端口启动，占用则自动递增重试"""
    port = start_port
    while True:
        try:
            write_port_file(port)
            logger.info(f"应用将在端口 {port} 上启动")
            app.run(
                host='0.0.0.0',
                port=port,
                debug=False,
                threaded=True,
            )
            break  # app.run 是阻塞的，正常退出才到这里
        except OSError as e:
            if 'Address already in use' in str(e) or 'address in use' in str(e).lower():
                logger.warning(f"端口 {port} 被占用，尝试 {port + 1}...")
                port += 1
                if port > start_port + PORT_RANGE:
                    raise RuntimeError(f"无法在 {start_port}-{start_port + PORT_RANGE} 找到空闲端口")
            else:
                raise


def main():
    try:
        os.chdir(current_dir)
        logger.info(f"已切换工作目录到: {os.getcwd()}")
        logger.info("正在创建应用实例...")
        app = create_app()
        try_start_app(app, DEFAULT_PORT)
    except Exception as e:
        logger.error(f"应用启动失败: {str(e)}", exc_info=True)
        raise


if __name__ == '__main__':
    main()