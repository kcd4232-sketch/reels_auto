"""저작권 걱정 없는 기본 효과음 7개를 직접 합성해 만듭니다(48kHz WAV).

효과음 폴더가 따로 없는 사람을 위한 시작용이다. 마음에 드는 효과음(CapCut 라이브러리, 무료 효과음 사이트 등)이
있으면 그 파일을 쓰는 게 더 좋다. 파일마다 소리가 시작하는 지점(타격점)이 0.00~0.01초라 박자 맞추기가 쉽다.

  snap.wav    딱(핑거 스냅 느낌)  챕터 전환·결과 공개
  click.wav   짧은 클릭          같은 챕터 안 장면 전환·조작
  pop.wav     통                  글자·카드 등장(자주 쓰지 않기)
  whoosh.wav  휙                  화면 전환(잦으면 안 됨)
  ding.wav    띠링               점수가 오를 때·감탄
  tick.wav    째깍               숫자 굴리기(짧게 여러 번 겹쳐 쓰지 않기)
  buzz.wav    땡                  안 됨·❌

사용 예:
  python make_sfx.py 편집/sfx
"""
import argparse
import sys
import wave
from pathlib import Path

import numpy as np

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

SR = 48000
RNG = np.random.default_rng(7)      # 매번 같은 소리


def t_(dur):
    return np.arange(int(SR * dur)) / SR


def env(dur, attack, decay):
    t = t_(dur)
    a = np.clip(t / max(attack, 1e-4), 0, 1)
    return a * np.exp(-np.maximum(0, t - attack) / decay)


def band(x, lo, hi):
    """FFT로 lo~hi Hz만 남긴다."""
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    X[(f < lo) | (f > hi)] = 0
    return np.fft.irfft(X, len(x))


def snap():
    d = 0.35
    n = RNG.standard_normal(len(t_(d)))
    body = band(n, 1800, 4200) * env(d, 0.0008, 0.035)
    crack = band(n, 4000, 12000) * env(d, 0.0003, 0.006) * 0.8
    tone = np.sin(2 * np.pi * 2600 * t_(d)) * env(d, 0.0005, 0.02) * 0.25
    return body + crack + tone


def click():
    d = 0.08
    n = RNG.standard_normal(len(t_(d)))
    return band(n, 2500, 9000) * env(d, 0.0003, 0.004) + np.sin(2 * np.pi * 3200 * t_(d)) * env(d, 0.0003, 0.012) * 0.5


def pop():
    d = 0.18
    t = t_(d)
    f = 320 + 700 * np.exp(-t / 0.025)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * env(d, 0.001, 0.05)


def whoosh():
    d = 0.55
    t = t_(d)
    n = RNG.standard_normal(len(t))
    shape = np.sin(np.pi * np.clip(t / d, 0, 1)) ** 2
    lowmix = band(n, 200, 1500)
    highmix = band(n, 1500, 7000)
    sweep = np.clip(t / d, 0, 1)
    return (lowmix * (1 - sweep) + highmix * sweep * 0.7) * shape


def ding():
    d = 0.9
    t = t_(d)
    out = np.zeros(len(t))
    for start, f0 in ((0.0, 1568.0), (0.09, 2093.0)):      # G6 → C7, 실로폰 느낌 배음
        k = t >= start
        tt = t[k] - start
        out[k] += (np.sin(2 * np.pi * f0 * tt) * np.exp(-tt / 0.28)
                   + 0.35 * np.sin(2 * np.pi * f0 * 3.93 * tt) * np.exp(-tt / 0.05)) * np.clip(tt / 0.002, 0, 1)
    return out


def tick():
    d = 0.05
    n = RNG.standard_normal(len(t_(d)))
    return band(n, 3000, 10000) * env(d, 0.0002, 0.003) + np.sin(2 * np.pi * 4200 * t_(d)) * env(d, 0.0002, 0.006) * 0.6


def buzz():
    d = 0.42
    t = t_(d)
    sq = np.sign(np.sin(2 * np.pi * 196 * t)) * 0.6 + np.sin(2 * np.pi * 392 * t) * 0.3
    return band(sq, 80, 3000) * np.clip(t / 0.005, 0, 1) * np.clip((d - t) / 0.06, 0, 1)


SOUNDS = dict(snap=snap, click=click, pop=pop, whoosh=whoosh, ding=ding, tick=tick, buzz=buzz)


def write(path, x, peak_db=-3.0):
    x = x / max(1e-9, np.max(np.abs(x))) * 10 ** (peak_db / 20)
    pcm = (np.clip(x, -1, 1) * 32767).astype('<i2')
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def main():
    C.setup_console()
    ap = argparse.ArgumentParser(description='기본 효과음 합성')
    ap.add_argument('out', nargs='?', default='편집/sfx', help='저장할 폴더(기본: 편집/sfx)')
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, fn in SOUNDS.items():
        write(out / f'{name}.wav', fn())
    print(f'효과음 {len(SOUNDS)}개를 만들었습니다: {out.resolve()}')
    print('  ' + ', '.join(f'{k}.wav' for k in SOUNDS))
    print('  CapCut에 넣을 때 기본 소리 크기는 -20dB(특별한 순간만 -15dB).')


if __name__ == '__main__':
    main()
