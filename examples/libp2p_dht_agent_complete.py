"""
完整的libp2p + DHT Agent通信实现示例

这个示例展示了如何结合libp2p和libp2p-kad-dht实现agent之间的通信。

安装依赖:
    pip install libp2p

使用步骤:
1. 启动第一个agent:
   python libp2p_dht_agent_complete.py --port 4001 --dht-port 8468

2. 启动第二个agent:
   python libp2p_dht_agent_complete.py --port 4002 --dht-port 8469

3. 使用peer_id向另一个agent发送消息（需要知道目标的peer_id）
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
from libp2p.kad_dht.kad_dht import KadDHT, DHTMode
from libp2p.network.stream.exceptions import StreamEOF
from libp2p.network.stream.net_stream import INetStream
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.peer.id import ID as PeerID
from libp2p.records.validator import Validator, NamespacedValidator
from libp2p.records.pubkey import PublicKeyValidator
from libp2p.tools.async_service import background_trio_service

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(levelname)s] - %(message)s'
)
logger = logging.getLogger(__name__)

# Agent通信协议ID
AGENT_PROTOCOL = TProtocol("/w3connect/agent/1.0.0")
MAX_READ_LEN = 2**32 - 1

# IPFS bootstrap节点（多个选项，包括DNS和IP地址格式）
BOOTSTRAP_NODES = [
    # DNS格式
    # "/dnsaddr/bootstrap.libp2p.io/p2p/QmNnooDu7bfjPFoTZYxMNLWUQJyrVwtbZg5gBMjTezGAJN",
    # "/dnsaddr/bootstrap.libp2p.io/p2p/QmQCU2EcMqAqQPR2i9bChDtGNJchTbq5TbXJJ16u19uLTa",
    # "/dnsaddr/bootstrap.libp2p.io/p2p/QmbLHAnMoJPWSCR5Zhtx6BHJX9KiKNN6tpvbUcqanj75Nb",
    # IP地址格式（更可靠，不依赖DNS解析）
    "/ip4/104.131.131.82/tcp/4001/p2p/QmaCpDMGvV2BGHeYERUEnRQAwe3N8SzbUtfsmvsqQLuvuJ",
    "/ip4/128.199.219.111/tcp/4001/p2p/QmSoLV4Bbm51jM9C4gDYZQ9Cy3U6aXMJDAbzgu2fzaDs64",
    "/ip4/104.236.76.40/tcp/4001/p2p/QmSoLV4Bbm51jM9C4gDYZQ9Cy3U6aXMJDAbzgu2fzaDs64",
    "/ip4/178.62.158.247/tcp/4001/p2p/QmSoLer265NRgSp2LA3dPaeykiS1J6DifTC88f5uVQKNAd",
]


class DHTAgent:
    """使用DHT的Agent节点 - 完整实现"""
    
    def __init__(
        self, 
        listen_addr: str = "/ip4/0.0.0.0/tcp/0", 
        dht_port: Optional[int] = None,
        bootstrap_nodes: Optional[list[str]] = None
    ):
        """
        初始化Agent
        
        Args:
            listen_addr: libp2p监听地址
            dht_port: DHT端口（如果提供则启用DHT）
            bootstrap_nodes: 自定义bootstrap节点列表（如果为None则使用默认列表）
        """
        self.listen_addr = listen_addr
        self.enable_dht = dht_port is not None
        self.bootstrap_nodes = bootstrap_nodes or BOOTSTRAP_NODES
        self.host = None
        self.dht = None
        self.dht_manager = None
        self.message_handlers: Dict[str, Callable] = {}
        self.connected_peers: Dict[str, Any] = {}
        self.running = False
        
    async def initialize(self):
        """初始化libp2p host"""
        logger.info("=" * 60)
        logger.info("正在初始化Agent")
        logger.info("=" * 60)
        
        # 步骤1: 创建libp2p host
        self.host = new_host()
        listen_addrs = [multiaddr.Multiaddr(self.listen_addr)]
        
        async with self.host.run(listen_addrs=listen_addrs), trio.open_nursery() as nursery:
            # 设置stream处理器
            self.host.set_stream_handler(AGENT_PROTOCOL, self._handle_stream)
            
            peer_id = self.host.get_id()
            peer_id_str = peer_id.to_string()
            logger.info(f"✓ Peer ID: {peer_id_str}")
            
            # 显示监听地址
            addrs = self.host.get_addrs()
            for addr in addrs:
                logger.info(f"✓ 监听地址: {addr}/p2p/{peer_id_str}")
            
            # 步骤3: 连接到bootstrap节点
            logger.info("\n正在连接到bootstrap节点...")
            await self._connect_bootstrap_nodes()
            
            # 步骤2: 初始化DHT（使用libp2p-kad-dht）
            if self.enable_dht:
                await self._initialize_libp2p_dht(nursery)
            
            # 步骤4: 在DHT中注册自己
            if self.dht:
                logger.info("\n正在DHT中注册自己...")
                await self._register_in_dht()
            
            self.running = True
            logger.info("\n" + "=" * 60)
            logger.info("Agent已启动，等待消息...")
            logger.info("=" * 60 + "\n")
            
            # 保持运行（DHT服务在后台运行）
            await trio.sleep_forever()
    
    async def _initialize_libp2p_dht(self, nursery: trio.Nursery):
        """
        步骤2: 初始化libp2p KadDHT
        
        使用libp2p自带的KadDHT实现，基于trio，与libp2p完全兼容
        """
        try:
            # 创建自定义validator用于agent信息存储
            class AgentValidator(Validator):
                """Validator for agent information in DHT"""
                def validate(self, key: str, value: bytes) -> None:
                    if not value:
                        raise ValueError("Value cannot be empty")
                    # 可以添加更多验证逻辑
                    try:
                        data = json.loads(value.decode('utf-8'))
                        if 'peer_id' not in data:
                            raise ValueError("Invalid agent info format")
                    except (json.JSONDecodeError, UnicodeDecodeError) as e:
                        raise ValueError(f"Invalid value format: {e}")
                
                def select(self, key: str, values: list[bytes]) -> int:
                    # 选择最新的值（可以根据timestamp选择）
                    return 0
            
            # 创建NamespacedValidator，包含默认的pk validator和自定义的agent validator
            validator = NamespacedValidator({
                "pk": PublicKeyValidator(),
                "agent": AgentValidator()
            })
            
            # 创建DHT实例（SERVER模式），传入validator
            self.dht = KadDHT(
                self.host, 
                DHTMode.SERVER, 
                enable_random_walk=True,
                validator=validator,
                validator_changed=True
            )
            logger.info("✓ 已注册agent命名空间validator")
            
            # 将已连接的peer添加到routing table
            for peer_id in self.host.get_peerstore().peer_ids():
                await self.dht.routing_table.add_peer(peer_id)
            
            # 启动DHT服务（在nursery中作为后台任务运行）
            async def run_dht():
                async with background_trio_service(self.dht):
                    logger.info("✓ libp2p KadDHT已启动")
                    # 等待一小段时间确保DHT完全启动
                    await trio.sleep(1)
                    # 保持DHT运行
                    await trio.sleep_forever()
            
            nursery.start_soon(run_dht)
            # 等待一小段时间确保DHT启动
            await trio.sleep(0.5)
            
        except Exception as e:
            logger.error(f"DHT初始化失败: {e}")
            import traceback
            traceback.print_exc()
            self.dht = None
    
    async def _connect_bootstrap_nodes(self):
        """步骤3: 连接到bootstrap节点"""
        connected_count = 0
        
        logger.info(f"尝试连接到 {len(self.bootstrap_nodes)} 个bootstrap节点...")
        
        for bootstrap_addr_str in self.bootstrap_nodes:
            try:
                bootstrap_addr = multiaddr.Multiaddr(bootstrap_addr_str)
                peer_info = info_from_p2p_addr(bootstrap_addr)
                
                peer_id_short = peer_info.peer_id.to_string()[:20]
                logger.info(f"  连接: {bootstrap_addr_str[:60]}... ({peer_id_short}...)")
                
                # 设置连接超时（5秒）
                with trio.fail_after(5.0):
                    await self.host.connect(peer_info)
                
                connected_count += 1
                logger.info(f"  ✓ 连接成功")
                
                self.connected_peers[peer_info.peer_id.to_string()] = peer_info
                
            except trio.TooSlowError:
                logger.warning(f"  ✗ 连接超时")
            except Exception as e:
                error_msg = str(e)
                # 截断过长的错误信息
                if len(error_msg) > 100:
                    error_msg = error_msg[:100] + "..."
                logger.warning(f"  ✗ 连接失败: {error_msg}")
        
        logger.info(f"\n✓ 已连接到 {connected_count}/{len(self.bootstrap_nodes)} 个bootstrap节点")
        
        if connected_count == 0:
            logger.warning("⚠️  警告: 未能连接到任何bootstrap节点")
            logger.warning("   这可能是正常的，如果:")
            logger.warning("   1. 你在本地网络环境中测试")
            logger.warning("   2. 防火墙阻止了连接")
            logger.warning("   3. 网络环境无法访问公共bootstrap节点")
            logger.warning("   你可以:")
            logger.warning("   - 使用 --bootstrap 参数指定本地或其他可访问的节点")
            logger.warning("   - 或者直接使用 --peer-addr 连接其他已知的agent")
    
    async def _register_in_dht(self):
        """步骤4: 在DHT中注册自己"""
        if not self.dht:
            return
        
        try:
            peer_id_str = self.host.get_id().to_string()
            # 准备agent信息
            agent_info = {
                'peer_id': peer_id_str,
                'addrs': [str(addr) for addr in self.host.get_addrs()],
                'timestamp': time.time()
            }
            
            # 存储到DHT（key使用peer_id：/agent/peer_id）
            key = f"/agent/{peer_id_str}"
            value = json.dumps(agent_info).encode('utf-8')
            await self.dht.put_value(key, value)
            logger.info(f"✓ 已在DHT中注册: {peer_id_str[:20]}... (key: {key})")
            
        except Exception as e:
            logger.error(f"DHT注册失败: {e}")
            import traceback
            traceback.print_exc()
    
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
            'from': self.host.get_id().to_string() if self.host else 'unknown',
            'timestamp': time.time(),
            'original_message': message
        }
    
    def register_message_handler(self, msg_type: str, handler: Callable):
        """注册自定义消息处理器"""
        self.message_handlers[msg_type] = handler
        logger.info(f"已注册消息处理器: {msg_type}")
    
    async def find_agent_in_dht(self, target_peer_id: str) -> Optional[Dict]:
        """
        步骤5: 通过DHT查找目标agent
        
        Args:
            target_peer_id: 目标peer ID
        """
        if not self.dht:
            logger.warning("DHT未初始化，无法查找agent")
            return None
        
        try:
            logger.info(f"🔍 在DHT中查找peer: {target_peer_id[:20]}...")
            # key使用peer_id
            key = f"/agent/{target_peer_id}"
            value_bytes = await self.dht.get_value(key)
            
            if value_bytes:
                agent_info = json.loads(value_bytes.decode('utf-8'))
                logger.info(f"   ✓ 找到peer: {agent_info.get('peer_id', 'N/A')[:20]}...")
                return agent_info
            else:
                logger.warning(f"   ✗ 未找到peer: {target_peer_id[:20]}...")
                return None
                
        except Exception as e:
            logger.error(f"DHT查找失败: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    async def send_message_to_agent(
        self, 
        target_peer_id: str, 
        message: Dict,
        use_dht: bool = True
    ) -> Optional[Dict]:
        """
        步骤6: 向目标agent发送消息
        
        Args:
            target_peer_id: 目标peer ID
            message: 要发送的消息字典
            use_dht: 是否使用DHT查找agent（如果False，需要直接提供peer地址）
        """
        try:
            peer_id = None
            peer_info = None
            
            if use_dht:
                # 通过DHT查找
                agent_info = await self.find_agent_in_dht(target_peer_id)
                if not agent_info:
                    return None
                
                # 解析peer信息
                peer_id_str = agent_info['peer_id']
                peer_id = PeerID.from_base58(peer_id_str)
                
                # 创建peer_info
                addrs = [multiaddr.Multiaddr(addr) for addr in agent_info['addrs']]
                peer_info = info_from_p2p_addr(addrs[0])
            else:
                # 直接使用已知的peer_id
                peer_id = PeerID.from_base58(target_peer_id)
                if target_peer_id in self.connected_peers:
                    peer_info = self.connected_peers[target_peer_id]
                else:
                    logger.error(f"未找到已连接的peer: {target_peer_id[:20]}...")
                    return None
            
            # 如果还没有连接，先建立连接
            peer_id_str = peer_id.to_string()
            if peer_id_str not in self.connected_peers:
                logger.info(f"🔗 正在连接到peer {peer_id_str[:20]}...")
                await self.host.connect(peer_info)
                self.connected_peers[peer_id_str] = peer_info
                logger.info(f"   ✓ 连接成功")
            
            # 创建stream并发送消息
            logger.info(f"📤 正在向peer {peer_id_str[:20]}...发送消息...")
            stream = await self.host.new_stream(peer_id, [AGENT_PROTOCOL])
            
            try:
                # 添加元数据
                message['from'] = self.host.get_id().to_string() if self.host else 'unknown'
                message['to'] = target_peer_id
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
            'from': agent.host.get_id().to_string() if agent.host else 'unknown',
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
        print("  send <peer_id> <message>  - 发送消息")
        print("  find <peer_id>            - 在DHT中查找peer")
        print("  list                      - 列出已连接的peer")
        print("  quit                      - 退出")
        print("=" * 60 + "\n")
        
        while agent.running:
            try:
                # 注意：这里简化了，实际应该使用异步输入
                # 在生产环境中，可以使用asyncio的stdin处理
                await trio.sleep(1)
            except KeyboardInterrupt:
                break


async def run_agent(
    listen_addr: str, 
    dht_port: Optional[int] = None,
    bootstrap_nodes: Optional[list[str]] = None
):
    """运行agent节点"""
    agent = DHTAgent(
        listen_addr=listen_addr, 
        dht_port=dht_port,
        bootstrap_nodes=bootstrap_nodes
    )
    
    # 注册示例消息处理器
    async def handle_ping(message: Dict, peer_id: PeerID) -> Dict:
        return {
            'type': 'pong',
            'from': agent.host.get_id().to_string() if agent.host else 'unknown',
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
  # 启动agent（启用DHT）
  python libp2p_dht_agent_complete.py --port 4001 --dht-port 8468
  
  # 使用自定义bootstrap节点
  python libp2p_dht_agent_complete.py --port 4001 --bootstrap /ip4/127.0.0.1/tcp/4002/p2p/QmXXX...
  
  # 不使用DHT（仅作为普通节点）
  python libp2p_dht_agent_complete.py --port 4001
        """
    )
    parser.add_argument(
        "--port",
        type=int,
        default=4001,
        help="libp2p监听端口（默认: 4001）"
    )
    parser.add_argument(
        "--dht-port",
        type=int,
        default=None,
        help="启用DHT（提供任意端口号即可，实际使用libp2p-kad-dht）"
    )
    parser.add_argument(
        "--bootstrap",
        type=str,
        nargs="*",
        help="自定义bootstrap节点地址（可以指定多个，用空格分隔）"
    )
    
    args = parser.parse_args()
    
    listen_addr = f"/ip4/0.0.0.0/tcp/{args.port}"
    
    # 处理自定义bootstrap节点
    bootstrap_nodes = None
    if args.bootstrap:
        bootstrap_nodes = args.bootstrap
        logger.info(f"使用自定义bootstrap节点: {len(bootstrap_nodes)} 个")
    
    try:
        trio.run(run_agent, listen_addr, args.dht_port, bootstrap_nodes)
    except KeyboardInterrupt:
        logger.info("\n正在关闭...")


if __name__ == "__main__":
    main()

