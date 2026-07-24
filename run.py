#!/usr/bin/env python3
"""SOCKS5 Proxy Manager — Launch admin dashboard + shop."""
import multiprocessing, sys, os, threading, logging, argparse

if sys.platform == 'win32':
    multiprocessing.freeze_support()

_base = os.path.dirname(os.path.abspath(__file__)) if '__file__' in dir() else os.path.dirname(sys.executable)
sys.path.insert(0, _base)
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(name)-12s %(levelname)-7s %(message)s')
log = logging.getLogger('run')

def main():
    parser = argparse.ArgumentParser(description='SOCKS5 Proxy Manager')
    parser.add_argument('-p','--port', type=int, default=8888)
    parser.add_argument('--shop-port', type=int, default=8889)
    parser.add_argument('--host', default='127.0.0.1')
    args = parser.parse_args()

    import config as cfg
    cfg.WEB_PORT = args.port
    cfg.SHOP_PORT = args.shop_port

    from shop import start_shop
    threading.Thread(target=start_shop, args=(args.host, args.shop_port), daemon=True).start()
    log.info(f'Shop:  http://{args.host}:{args.shop_port}')

    from web_dashboard import start_web
    log.info(f'Admin: http://{args.host}:{args.port}  (login: admin / admin)')
    start_web(host=args.host, port=args.port)

if __name__ == '__main__':
    main()
