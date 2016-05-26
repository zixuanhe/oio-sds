from hashlib import md5
from oiopy import set_logger
from oiopy.storage_method import STORAGE_METHODS
from oiopy.ec import ECChunkWriteHandler, ECChunkDownloadHandler
from oiopy.replication import ReplicatedChunkWriteHandler
from oiopy.io import ChunkReader

from werkzeug.wrappers import Request, Response


SYS_PREFIX = 'x-oio-chunk-meta-'

sys_headers = {
    'chunk_pos': '%schunk-pos' % SYS_PREFIX,
    'nb_chunks': '%schunks-nb' % SYS_PREFIX,
    'chunk_size': '%schunk-size' % SYS_PREFIX,
    'content_id': '%scontent-id' % SYS_PREFIX,
    'content_mime_type': '%scontent-mime-type' % SYS_PREFIX,
    'content_length': '%scontent-length' % SYS_PREFIX,
    'content_chunkmethod': '%scontent-chunk-method' % SYS_PREFIX,
    'content_path': '%scontent-path' % SYS_PREFIX,
    'content_chunksnb': '%scontent-chunksnb' % SYS_PREFIX,
    'content_hash': '%scontent-hash' % SYS_PREFIX,
    'content_version': '%scontent-version' % SYS_PREFIX,
    'content_policy': '%scontent-storage-policy' % SYS_PREFIX,
    'container_id': '%scontainer-id' % SYS_PREFIX,
}


def load_sysmeta(request):
    h = request.headers
    try:
        sysmeta = {}
        sysmeta['id'] = h[sys_headers['content_id']]
        sysmeta['version'] = h[sys_headers['content_version']]
        sysmeta['content_path'] = h[sys_headers['content_path']]
        sysmeta['content_length'] = h.get(sys_headers['content_length'], "0")
        sysmeta['chunk_method'] = h[sys_headers['content_chunkmethod']]
        sysmeta['mime_type'] = h[sys_headers['content_mime_type']]
        sysmeta['policy'] = h[sys_headers['content_policy']]
        sysmeta['content_chunksnb'] = h.get(sys_headers['content_chunksnb'],
                                            "1")
        sysmeta['container_id'] = h[sys_headers['container_id']]
        return sysmeta
    except KeyError:
        print h
        raise


def load_meta_chunk(request, nb_chunks, pos=None):
    h = request.headers
    meta_chunk = []
    for i in xrange(nb_chunks):
        chunk_url = h['%schunk-%s' % (SYS_PREFIX, i)]
        chunk_pos = '%s.%d' % (pos, i) if pos else str(i)
        chunk = {
            'url': chunk_url,
            'pos': chunk_pos,
            'num': i
        }
        meta_chunk.append(chunk)
    return meta_chunk


def part_iter_to_bytes_iter(stream):
    for part in stream:
        for x in part['iter']:
            yield x


class ECD(object):
    def __init__(self, conf):
        self.conf = conf

    def write_ec_meta_chunk(self, source, size, storage_method, sysmeta,
                            meta_chunk):
        meta_checksum = md5()
        handler = ECChunkWriteHandler(sysmeta, meta_chunk, meta_checksum,
                                      storage_method)
        bytes_transferred, checksum, chunks = handler.stream(source, size)
        return Response("OK")

    def write_repli_meta_chunk(self, source, size, storage_method, sysmeta,
                               meta_chunk):
        meta_checksum = md5()
        handler = ReplicatedChunkWriteHandler(sysmeta, meta_chunk,
                                              meta_checksum)
        bytes_transferred, checksum, chunks = handler.stream(source, size)
        return Response("OK")

    def read_ec_meta_chunk(self, storage_method, meta_chunk):
        meta_start = None
        meta_end = None
        headers = {}
        handler = ECChunkDownloadHandler(storage_method, meta_chunk,
                                         meta_start, meta_end, headers)
        stream = handler.get_stream()
        return Response(part_iter_to_bytes_iter(stream), 200)

    def read_meta_chunk(self, storage_method, meta_chunk):
        headers = {}
        handler = ChunkReader(meta_chunk, headers)
        stream = handler.get_iter()
        return Response(part_iter_to_bytes_iter(stream), 200)

    def dispatch_request(self, req):
        if req.method == 'PUT':
            source = req.input_stream
            size = req.content_length
            sysmeta = load_sysmeta(req)
            storage_method = STORAGE_METHODS.load(sysmeta['chunk_method'])

            if storage_method.ec:
                if not size:
                    # FIXME: get chunk size from proxy
                    size = (storage_method.ec_nb_data * 10 *
                            storage_method.ec_segment_size)
                nb_chunks = (storage_method.ec_nb_data +
                             storage_method.ec_nb_parity)
                pos = req.headers[sys_headers['chunk_pos']]
                meta_chunk = load_meta_chunk(req, nb_chunks, pos)
                return self.write_ec_meta_chunk(source, size, storage_method,
                                                sysmeta, meta_chunk)
            else:
                # FIXME: check and fix size
                meta_chunk = load_meta_chunk(req, nb_chunks)
                return self.write_repli_meta_chunk(source, size,
                                                   storage_method, sysmeta,
                                                   meta_chunk)

        elif req.method == 'GET':
            chunk_method = req.headers[sys_headers['content_chunkmethod']]
            storage_method = STORAGE_METHODS.load(chunk_method)
            if storage_method.ec:
                nb_chunks = storage_method.ec_nb_data + \
                    storage_method.ec_nb_parity
                meta_chunk = load_meta_chunk(req, nb_chunks)
                meta_chunk[0]['size'] = \
                    int(req.headers[sys_headers['chunk_size']])
                return self.read_ec_meta_chunk(storage_method, meta_chunk)
            else:
                nb_chunks = int(req.headers[sys_headers['nb_chunks']])
                meta_chunk = load_meta_chunk(req, nb_chunks)
                return self.read_meta_chunk(storage_method, meta_chunk)
        else:
            return Response(status=403)

    def wsgi_app(self, environ, start_response):
        request = Request(environ)
        response = self.dispatch_request(request)
        return response(environ, start_response)

    def __call__(self, environ, start_response):
        return self.wsgi_app(environ, start_response)


def create_app():
    app = ECD({})
    set_logger()
    return app

if __name__ == '__main__':
    from werkzeug.serving import run_simple
    app = create_app()
    run_simple('127.0.0.1', 5000, app, use_debugger=True, use_reloader=True)
