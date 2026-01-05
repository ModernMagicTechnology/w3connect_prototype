"""
完整的libp2p + DHT Agent通信实现示例

这个示例展示了如何结合libp2p和kademlia DHT实现agent之间的通信。

安装依赖:
    pip install libp2p kademlia

使用步骤:
1. 启动第一个agent（服务器模式）:
   python libp2p_dht_agent_complete.py --agent-id agent1 --port 4001

2. 启动第二个agent（服务器模式）:
   python libp2p_dht_agent_complete.py --agent-id agent2 --port 4002

3. 从一个agent向另一个发送消息（需要知道目标agent_id）
"""

import argparse
import asyncio
import json
import logging
from typing import Optional, Dict, Any, Callable
import time

import multiaddr
import trio
from libp2p import new_host
from libp2p.custom_types import TProtocol
from libp2p.network.stream.exceptions import StreamEOF
from libp2p.network.stream.net_stream import INetStream
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

# IPFS bootstrap节点
BOOTSTRAP_NODES = [
    "/dnsaddr/bootstrap.libp2p.io/p2p/QmNnooDu7bfjPFoTZYxMNLWUQJyrVwtbZg5gBMjTezGAJN",
    "/dnsaddr/bootstrap.libp2p.io/p2p/QmQCU2EcMqAqQPR2i9bChDtGNJchTbq5TbXJJ16u19uLTa",
]


class DHTAgent:
    """使用DHT的Agent节点 - 完整实现"""
    
    def __init__(
        self, 
        listen_addr: str = "/ip4/0.0.0.0/tcp/0", 
        agent_id: Optional[str] = None,
        dht_port: Optional[int] = None
    ):
        """
        初始化Agent
        
        Args:
            listen_addr: libp2p监听地址
            agent_id: Agent的唯一标识符
            dht_port: DHT监听端口（如果使用kademlia）
        """
        self.listen_addr = listen_addr
        self.agent_id = agent_id or f"agent_{int(time.time())}"
        self.dht_port = dht_port
        self.host = None
        self.dht = None
        self.message_handlers: Dict[str, Callable] = {}
        self.connected_peers: Dict[str, Any] = {}
        self.running = False
        
    async def initialize(self):
        """初始化libp2p host"""
        logger.info("=" * 60)
        logger.info(f"正在初始化Agent: {self.agent_id}")
        logger.info("=" * 60)
        
        # 步骤1: 创建libp2p host
        self.host = new_host()
        listen_addrs = [multiaddr.Multiaddr(self.listen_addr)]
        
        async with self.host.run(listen_addrs=listen_addrs):
            # 设置stream处理器
            self.host.set_stream_handler(AGENT_PROTOCOL, self._handle_stream)
            
            peer_id = self.host.get_id()
            logger.info(f"✓ Peer ID: {peer_id.to_string()}")
            logger.info(f"✓ Agent ID: {self.agent_id}")
            
            # 显示监听地址
            addrs = self.host.get_addrs()
            for addr in addrs:
                logger.info(f"✓ 监听地址: {addr}/p2p/{peer_id.to_string()}")
            
            # 步骤2: 初始化DHT（如果使用kademlia）
            if self.dht_port:
                await self._initialize_kademlia_dht()
            
            # 步骤3: 连接到bootstrap节点
            logger.info("\n正在连接到bootstrap节点...")
            await self._connect_bootstrap_nodes()
            
            # 步骤4: 在DHT中注册自己
            if self.dht:
                logger.info("\n正在DHT中注册自己...")
                await self._register_in_dht()
            
            self.running = True
            logger.info("\n" + "=" * 60)
            logger.info("Agent已启动，等待消息...")
            logger.info("=" * 60 + "\n")
            
            # 保持运行
            await trio.sleep_forever()
    
    async def _initialize_kademlia_dht(self):
        """
        步骤2: 初始化Kademlia DHT
        
        注意：这需要安装kademlia库: pip install kademlia
        如果不想使用kademlia，可以注释掉这部分，使用其他DHT实现
        """
        try:
            from kademlia.network import Server
            
            self.dht = Server()
            # 启动DHT服务器
            await self.dht.listen(self.dht_port)
            logger.info(f"✓ Kademlia DHT已启动，端口: {self.dht_port}")
            
            # 连接到bootstrap节点（如果有其他DHT节点）
            # bootstrap_node = ("127.0.0.1", 8468)  # 示例
            # await self.dht.bootstrap([bootstrap_node])
            
        except ImportError:
            logger.warning("kademlia库未安装，跳过DHT初始化")
            logger.warning("安装命令: pip install kademlia")
            self.dht = None
        except Exception as e:
            logger.error(f"DHT初始化失败: {e}")
            self.dht = None
    
    async def _connect_bootstrap_nodes(self):
        """步骤3: 连接到bootstrap节点"""
        connected_count = 0
        
        for bootstrap_addr_str in BOOTSTRAP_NODES:
            try:
                bootstrap_addr = multiaddr.Multiaddr(bootstrap_addr_str)
                peer_info = info_from_p2p_addr(bootstrap_addr)
                
                logger.info(f"  连接: {peer_info.peer_id.to_string()[:20]}...")
                await self.host.connect(peer_info)
                connected_count += 1
                logger.info(f"  ✓ 连接成功")
                
                self.connected_peers[peer_info.peer_id.to_string()] = peer_info
                
            except Exception as e:
                logger.warning(f"  ✗ 连接失败: {str(e)[:50]}")
        
        logger.info(f"\n✓ 已连接到 {connected_count}/{len(BOOTSTRAP_NODES)} 个bootstrap节点")
    
    async def _register_in_dht(self):
        """步骤4: 在DHT中注册自己"""
        if not self.dht:
            return
        
        try:
            # 准备agent信息
            agent_info = {
                'peer_id': self.host.get_id().to_string(),
                'addrs': [str(addr) for addr in self.host.get_addrs()],
                'agent_id': self.agent_id,
                'timestamp': time.time()
            }
            
            # 存储到DHT（使用agent_id作为key）
            await self.dht.set(self.agent_id, json.dumps(agent_info))
            logger.info(f"✓ 已在DHT中注册: {self.agent_id}")
            
        except Exception as e:
            logger.error(f"DHT注册失败: {e}")
    
    async def _handle_stream(self, stream: INetStream):
        """处理接收到的stream消息"""
        peer_id_str = None
        try:
            peer_id = stream.muxed_conn.peer_id
            peer_id_str = peer_id.to_string()
            logger.info(f"\n📨 收到来自 {peer_id_str[:20]}... 的消息")
            
            # 读取消息
            data = await stream.read(MAX_READ_LEN)
            if data:
                try:
                    message = json.loads(data.decode('utf-8'))
                    logger.info(f"   消息类型: {message.get('type', 'unknown')}")
                    logger.info(f"   消息内容: {message.get('data', 'N/A')}")
                    
                    # 处理消息
                    msg_type = message.get('type', 'unknown')
                    if msg_type in self.message_handlers:
                        response = await self.message_handlers[msg_type](message, peer_id)
                    else:
                        response = await self._default_message_handler(message, peer_id)
                    
                    # 发送响应
                    if response:
                        response_data = json.dumps(response).encode('utf-8')
                        await stream.write(response_data)
                        logger.info(f"   ✓ 已发送响应")
                        
                except json.JSONDecodeError as e:
                    logger.error(f"   ✗ JSON解析失败: {e}")
                    await stream.write(b'{"error": "invalid json"}')
            
        except StreamEOF:
            logger.info(f"   Stream已关闭")
        except Exception as exc:
            logger.error(f"   ✗ 处理stream时出错: {exc}")
        finally:
            await stream.close()
    
    async def _default_message_handler(self, message: Dict, peer_id: PeerID) -> Dict:
        """默认消息处理器"""
        return {
            'type': 'response',
            'status': 'received',
            'from': self.agent_id,
            'timestamp': time.time(),
            'original_message': message
        }
    
    def register_message_handler(self, msg_type: str, handler: Callable):
        """注册自定义消息处理器"""
        self.message_handlers[msg_type] = handler
        logger.info(f"已注册消息处理器: {msg_type}")
    
    async def find_agent_in_dht(self, target_agent_id: str) -> Optional[Dict]:
        """
        步骤5: 通过DHT查找目标agent
        """
        if not self.dht:
            logger.warning("DHT未初始化，无法查找agent")
            return None
        
        try:
            logger.info(f"🔍 在DHT中查找agent: {target_agent_id}")
            agent_info_str = await self.dht.get(target_agent_id)
            
            if agent_info_str:
                agent_info = json.loads(agent_info_str)
                logger.info(f"   ✓ 找到agent: {agent_info.get('peer_id', 'N/A')[:20]}...")
                return agent_info
            else:
                logger.warning(f"   ✗ 未找到agent: {target_agent_id}")
                return None
                
        except Exception as e:
            logger.error(f"DHT查找失败: {e}")
            return None
    
    async def send_message_to_agent(
        self, 
        target_agent_id: str, 
        message: Dict,
        use_dht: bool = True
    ) -> Optional[Dict]:
        """
        步骤6: 向目标agent发送消息
        
        Args:
            target_agent_id: 目标agent ID
            message: 要发送的消息字典
            use_dht: 是否使用DHT查找agent（如果False，需要直接提供peer地址）
        """
        try:
            peer_id = None
            peer_info = None
            
            if use_dht:
                # 通过DHT查找
                agent_info = await self.find_agent_in_dht(target_agent_id)
                if not agent_info:
                    return None
                
                # 解析peer信息
                peer_id_str = agent_info['peer_id']
                peer_id = PeerID.from_base58(peer_id_str)
                
                # 创建peer_info
                addrs = [multiaddr.Multiaddr(addr) for addr in agent_info['addrs']]
                peer_info = info_from_p2p_addr(addrs[0])
            else:
                # 直接使用已知的peer_id（需要先连接）
                if target_agent_id in self.connected_peers:
                    peer_info = self.connected_peers[target_agent_id]
                    peer_id = peer_info.peer_id
                else:
                    logger.error(f"未找到已连接的peer: {target_agent_id}")
                    return None
            
            # 如果还没有连接，先建立连接
            peer_id_str = peer_id.to_string()
            if peer_id_str not in self.connected_peers:
                logger.info(f"🔗 正在连接到agent {target_agent_id}...")
                await self.host.connect(peer_info)
                self.connected_peers[peer_id_str] = peer_info
                logger.info(f"   ✓ 连接成功")
            
            # 创建stream并发送消息
            logger.info(f"📤 正在向agent {target_agent_id}发送消息...")
            stream = await self.host.new_stream(peer_id, [AGENT_PROTOCOL])
            
            try:
                # 添加元数据
                message['from'] = self.agent_id
                message['to'] = target_agent_id
                message['timestamp'] = time.time()
                
                # 发送消息
                message_data = json.dumps(message).encode('utf-8')
                await stream.write(message_data)
                logger.info(f"   ✓ 消息已发送")
                
                # 读取响应
                response_data = await stream.read(MAX_READ_LEN)
                if response_data:
                    response = json.loads(response_data.decode('utf-8'))
                    logger.info(f"   ✓ 收到响应: {response.get('status', 'N/A')}")
                    return response
                    
            except StreamEOF:
                logger.warning("   Stream已关闭")
            finally:
                await stream.close()
                
        except Exception as e:
            logger.error(f"发送消息时出错: {e}")
            return None


async def run_agent_interactive(agent: DHTAgent):
    """交互式运行agent"""
    # 注册示例消息处理器
    async def handle_ping(message: Dict, peer_id: PeerID) -> Dict:
        return {
            'type': 'pong',
            'from': agent.agent_id,
            'timestamp': time.time(),
            'original_timestamp': message.get('timestamp')
        }
    
    agent.register_message_handler('ping', handle_ping)
    
    # 启动agent
    async with trio.open_nursery() as nursery:
        nursery.start_soon(agent.initialize)
        
        # 等待一下让agent启动
        await trio.sleep(2)
        
        # 交互式命令循环
        print("\n" + "=" * 60)
        print("Agent命令:")
        print("  send <agent_id> <message>  - 发送消息")
        print("  find <agent_id>            - 在DHT中查找agent")
        print("  list                       - 列出已连接的peer")
        print("  quit                       - 退出")
        print("=" * 60 + "\n")
        
        while agent.running:
            try:
                # 注意：这里简化了，实际应该使用异步输入
                # 在生产环境中，可以使用asyncio的stdin处理
                await trio.sleep(1)
            except KeyboardInterrupt:
                break


async def run_agent(listen_addr: str, agent_id: str, dht_port: Optional[int] = None):
    """运行agent节点"""
    agent = DHTAgent(listen_addr=listen_addr, agent_id=agent_id, dht_port=dht_port)
    
    # 注册示例消息处理器
    async def handle_ping(message: Dict, peer_id: PeerID) -> Dict:
        return {
            'type': 'pong',
            'from': agent.agent_id,
            'timestamp': time.time(),
            'original_timestamp': message.get('timestamp')
        }
    
    agent.register_message_handler('ping', handle_ping)
    
    await agent.initialize()


def main():
    parser = argparse.ArgumentParser(
        description="使用libp2p和DHT的Agent通信示例",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:
  # 启动agent1
  python libp2p_dht_agent_complete.py --agent-id agent1 --port 4001 --dht-port 8468
  
  # 启动agent2
  python libp2p_dht_agent_complete.py --agent-id agent2 --port 4002 --dht-port 8469
  
  # 从一个agent向另一个发送消息（需要修改代码或使用API）
        """
    )
    parser.add_argument(
        "--port",
        type=int,
        default=4001,
        help="libp2p监听端口（默认: 4001）"
    )
    parser.add_argument(
        "--agent-id",
        default=f"agent_{int(time.time())}",
        help="Agent的唯一标识符"
    )
    parser.add_argument(
        "--dht-port",
        type=int,
        default=None,
        help="DHT监听端口（如果使用kademlia，默认: None）"
    )
    
    args = parser.parse_args()
    
    listen_addr = f"/ip4/0.0.0.0/tcp/{args.port}"
    
    try:
        trio.run(run_agent, listen_addr, args.agent_id, args.dht_port)
    except KeyboardInterrupt:
        logger.info("\n正在关闭...")


if __name__ == "__main__":
    main()

