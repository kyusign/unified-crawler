# -*- coding: utf-8 -*-
import functools

def apply_pytube_after_patch(logger=None):
    """pytube.innertube의 clientVersion과 기본 client를 after 상태로 강제."""
    try:
        import pytube.innertube as it

        versions = {
            'ANDROID':        '19.08.35',
            'IOS':            '19.08.35',
            'ANDROID_EMBED':  '19.08.35',
            'IOS_EMBED':      '19.08.35',
            'ANDROID_MUSIC':  '6.40.52',  # 공백 제거
            'IOS_MUSIC':      '6.41',
        }
        for k, v in versions.items():
            try:
                it._default_clients[k]['context']['client']['clientVersion'] = v
            except Exception:
                pass

        _orig_init = it.InnerTube.__init__
        @functools.wraps(_orig_init)
        def _patched_init(self, *args, **kwargs):
            if 'client' not in kwargs and (len(args) == 0 or args[0] is None):
                kwargs['client'] = 'ANDROID'
            return _orig_init(self, *args, **kwargs)

        it.InnerTube.__init__ = _patched_init

        if logger:
            logger.info("[pytube] innertube after-패치 적용 완료")
    except Exception as e:
        msg = f"[pytube] after-패치 적용 실패: {e}"
        (logger.exception if logger else print)(msg)
