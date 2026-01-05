"""
libp2p DHT Agent 客户端 - 用于向agent节点发送消息

使用方法:
1. 通过peer地址直接连接:
   python libp2p_dht_client.py --peer-addr /ip4/127.0.0.1/tcp/4001/p2p/QmXXX... --message "Hello"

2. 通过DHT查找agent:
   python libp2p_dht_client.py --dht-port 8468 --agent-id agent1 --message "Hello"

3. 发送ping消息:
   python libp2p_dht_client.py --peer-addr /ip4/127.0.0.1/tcp/4001/p2p/QmXXX... --ping

4. 发送自定义JSON消息:
   python libp2p_dht_client.py --peer-addr /ip4/127.0.0.1/tcp/4001/p2p/QmXXX... --json '{"type":"custom","data":"test"}'
"""

import argparse
import asyncio
import json
import logging
import time
from typing import Optional, Dict, Any

import multiaddr
import trio
from libp2p import new_host
from libp2p.custom_types import TProtocol
from libp2p.network.stream.exceptions import StreamEOF
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.peer.id import ID as PeerID

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(levelname)s] - %(message)s'
)
logger = logging.getLogger(__name__)

# Agent通信协议ID
AGENT_PROTOCOL = TProtocol("/w3connect/agent/1.0.0")
MAX_READ_LEN = 2**32 - 1


class AgentClient:
    """Agent客户端 - 用于发送消息到agent节点"""
    
    def __init__(self, listen_addr: str = "/ip4/0.0.0.0/tcp/0"):
        """
        初始化客户端
        
        Args:
            listen_addr: 客户端监听地址
        """
        self.listen_addr = listen_addr
        self.host = None
        self.dht = None
        
    def create_host(self):
        """创建libp2p host"""
        self.host = new_host()
        listen_addrs = [multiaddr.Multiaddr(self.listen_addr)]
        
        peer_id = self.host.get_id()
        logger.info(f"客户端已启动，Peer ID: {peer_id.to_string()}")
        
        return self.host.run(listen_addrs=listen_addrs)
    
    async def initialize_dht(self, dht_port: int):
        """
        初始化DHT客户端
        
        注意：kademlia使用asyncio，而libp2p使用trio，两者不兼容。
        此功能暂时不可用。请使用--peer-addr直接连接。
        """
        logger.error("=" * 60)
        logger.error("DHT功能暂时不可用")
        logger.error("=" * 60)
        logger.error("原因: kademlia库使用asyncio，而libp2p使用trio，两者不兼容")
        logger.error("")
        logger.error("解决方案:")
        logger.error("  1. 使用--peer-addr直接连接（推荐）")
        logger.error("  2. 或者使用trio-asyncio兼容层（需要额外配置）")
        logger.error("")
        logger.error("示例:")
        logger.error("  python libp2p_dht_client.py --peer-addr /ip4/127.0.0.1/tcp/4001/p2p/QmXXX... --message 'Hello'")
        logger.error("=" * 60)
        raise RuntimeError("DHT功能暂时不可用，请使用--peer-addr直接连接")
    
    async def find_agent_in_dht(self, agent_id: str) -> Optional[Dict]:
        """通过DHT查找agent"""
        if not self.dht:
            logger.error("DHT未初始化")
            return None
        
        try:
            logger.info(f"🔍 在DHT中查找agent: {agent_id}")
            agent_info_str = await self.dht.get(agent_id)
            
            if agent_info_str:
                agent_info = json.loads(agent_info_str)
                logger.info(f"   ✓ 找到agent: {agent_info.get('peer_id', 'N/A')[:20]}...")
                return agent_info
            else:
                logger.error(f"   ✗ 未找到agent: {agent_id}")
                return None
                
        except Exception as e:
            logger.error(f"DHT查找失败: {e}")
            return None
    
    async def send_message(
        self,
        peer_addr: Optional[str] = None,
        agent_id: Optional[str] = None,
        message: Dict[str, Any] = None
    ) -> Optional[Dict]:
        """
        发送消息到agent节点
        
        Args:
            peer_addr: 目标peer地址（格式: /ip4/127.0.0.1/tcp/4001/p2p/QmXXX...）
            agent_id: 目标agent ID（如果使用DHT查找）
            message: 要发送的消息字典
        """
        if not self.host:
            logger.error("Host未初始化")
            return None
        
        try:
            peer_info = None
            
            # 方式1: 通过peer地址直接连接
            if peer_addr:
                logger.info(f"🔗 连接到peer: {peer_addr}")
                peer_addr_multi = multiaddr.Multiaddr(peer_addr)
                peer_info = info_from_p2p_addr(peer_addr_multi)
            
            # 方式2: 通过DHT查找
            elif agent_id and self.dht:
                agent_info = await self.find_agent_in_dht(agent_id)
                if not agent_info:
                    return None
                
                # 从agent_info中获取peer地址
                peer_id_str = agent_info['peer_id']
                addrs = agent_info.get('addrs', [])
                if not addrs:
                    logger.error("Agent信息中没有地址")
                    return None
                
                # 使用第一个地址
                addr_str = addrs[0]
                # 构建完整的peer地址
                peer_addr_str = f"{addr_str}/p2p/{peer_id_str}"
                logger.info(f"🔗 连接到peer: {peer_addr_str}")
                peer_addr_multi = multiaddr.Multiaddr(peer_addr_str)
                peer_info = info_from_p2p_addr(peer_addr_multi)
            
            else:
                logger.error("必须提供peer_addr或agent_id（需要DHT）")
                return None
            
            # 连接到peer
            peer_id = peer_info.peer_id
            logger.info(f"   正在连接...")
            await self.host.connect(peer_info)
            logger.info(f"   ✓ 连接成功")
            
            # 创建stream并发送消息
            logger.info(f"📤 正在发送消息...")
            stream = await self.host.new_stream(peer_id, [AGENT_PROTOCOL])
            
            try:
                # 发送消息
                message_data = json.dumps(message).encode('utf-8')
                await stream.write(message_data)
                logger.info(f"   ✓ 消息已发送")
                
                # 读取响应
                response_data = await stream.read(MAX_READ_LEN)
                if response_data:
                    response = json.loads(response_data.decode('utf-8'))
                    logger.info(f"   ✓ 收到响应:")
                    logger.info(f"      {json.dumps(response, indent=2, ensure_ascii=False)}")
                    return response
                else:
                    logger.warning("   未收到响应")
                    return None
                    
            except StreamEOF:
                logger.warning("   Stream已关闭")
                return None
            finally:
                await stream.close()
                
        except Exception as e:
            logger.error(f"发送消息时出错: {e}")
            import traceback
            traceback.print_exc()
            return None


async def run_client(
    peer_addr: Optional[str] = None,
    agent_id: Optional[str] = None,
    dht_port: Optional[int] = None,
    message: Optional[str] = None,
    json_message: Optional[str] = None,
    ping: bool = False
):
    """运行客户端"""
    client = AgentClient()
    
    # 创建host并启动
    host_context = client.create_host()
    
    # 在host运行的上下文中执行
    async with host_context:
        # 初始化DHT（如果需要）
        if dht_port:
            await client.initialize_dht(dht_port)
        
        # 准备消息
        msg = None
        
        if ping:
            msg = {
                'type': 'ping',
                'data': 'ping request',
                'timestamp': time.time()
            }
        elif json_message:
            try:
                msg = json.loads(json_message)
            except json.JSONDecodeError as e:
                logger.error(f"JSON解析失败: {e}")
                return
        elif message:
            msg = {
                'type': 'message',
                'data': message,
                'timestamp': time.time()
            }
        else:
            logger.error("必须提供--message、--json或--ping参数")
            return
        
        # 发送消息
        response = await client.send_message(
            peer_addr=peer_addr,
            agent_id=agent_id,
            message=msg
        )
        
        if response:
            logger.info("\n✓ 消息发送成功")
        else:
            logger.error("\n✗ 消息发送失败")
        
        # 等待一小段时间确保消息发送完成
        await trio.sleep(0.5)


def main():
    parser = argparse.ArgumentParser(
        description="libp2p DHT Agent客户端 - 向agent节点发送消息",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:
  # 方式1: 通过peer地址发送消息
  python libp2p_dht_client.py --peer-addr /ip4/127.0.0.1/tcp/4001/p2p/QmXXX... --message "Hello"
  
  # 方式2: 通过DHT查找并发送消息
  python libp2p_dht_client.py --dht-port 8468 --agent-id agent1 --message "Hello"
  
  # 方式3: 发送ping消息
  python libp2p_dht_client.py --peer-addr /ip4/127.0.0.1/tcp/4001/p2p/QmXXX... --ping
  
  # 方式4: 发送自定义JSON消息
  python libp2p_dht_client.py --peer-addr /ip4/127.0.0.1/tcp/4001/p2p/QmXXX... --json '{"type":"custom","data":"test"}'
        """
    )
    
    parser.add_argument(
        "--peer-addr",
        type=str,
        help="目标peer地址（格式: /ip4/127.0.0.1/tcp/4001/p2p/QmXXX...）"
    )
    parser.add_argument(
        "--agent-id",
        type=str,
        help="目标agent ID（需要配合--dht-port使用）"
    )
    parser.add_argument(
        "--dht-port",
        type=int,
        help="DHT端口（用于查找agent）"
    )
    parser.add_argument(
        "--message",
        type=str,
        help="要发送的文本消息"
    )
    parser.add_argument(
        "--json",
        type=str,
        dest="json_message",
        help="要发送的JSON消息（字符串格式）"
    )
    parser.add_argument(
        "--ping",
        action="store_true",
        help="发送ping消息"
    )
    
    args = parser.parse_args()
    
    # 验证参数
    if not args.peer_addr and not args.agent_id:
        parser.error("必须提供--peer-addr或--agent-id（需要--dht-port）")
    
    if args.agent_id and not args.dht_port:
        parser.error("使用--agent-id时必须提供--dht-port")
    
    # 检查是否尝试使用DHT功能
    if args.agent_id or args.dht_port:
        logger.error("=" * 60)
        logger.error("⚠️  DHT功能暂时不可用")
        logger.error("=" * 60)
        logger.error("原因: kademlia库使用asyncio，而libp2p使用trio，两者不兼容")
        logger.error("")
        logger.error("请使用--peer-addr直接连接（推荐方式）")
        logger.error("")
        logger.error("示例:")
        logger.error("  python libp2p_dht_client.py --peer-addr /ip4/127.0.0.1/tcp/4001/p2p/QmXXX... --message 'Hello'")
        logger.error("")
        logger.error("获取peer地址的方法:")
        logger.error("  启动agent时会显示: /ip4/127.0.0.1/tcp/4001/p2p/QmXXX...")
        logger.error("=" * 60)
        return
    
    if not args.message and not args.json_message and not args.ping:
        parser.error("必须提供--message、--json或--ping参数")
    
    try:
        trio.run(
            run_client,
            args.peer_addr,
            args.agent_id,
            args.dht_port,
            args.message,
            args.json_message,
            args.ping
        )
    except KeyboardInterrupt:
        logger.info("\n正在关闭...")


if __name__ == "__main__":
    main()
