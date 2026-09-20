"""Приймальні тести TASK-30: монтаж із шаблонів.

Написані замовником ДО виконання. Виконавець їх не змінює. Дані вигадані.
"""
import importlib

import pytest

ep = importlib.import_module('content.edit_plan')


# ── кадри ─────────────────────────────────────────────────────────────

def test_frames():
    assert ep.frames(3.0) == 90 and ep.frames(0.01) == 1 and ep.frames(1.5, 25) == 38
    for bad in (0, -1):
        with pytest.raises(ValueError):
            ep.frames(bad)


def test_shot_filter_zoom_in():
    f = ep.shot_filter('zoom_in', 3.0, 0)
    assert f.startswith('[0:v]' + ep.FIT + ',') and f.endswith('setsar=1[v0]')
    assert "zoompan=z='min(zoom+0.0009,1.18)':d=90:s=1080x1920:fps=30" in f
    assert f.index('crop=1080:1920') < f.index('zoompan')      # FIT перед рухом


@pytest.mark.parametrize('template,fragment', [
    ('zoom_out', "z='if(eq(on,0),1.18,max(zoom-0.0009,1.0))'"),
    ('pan_right', "x='iw*0.18*on/60'"),
    ('static', 'zoompan=z=1:d=60'),
])
def test_shot_filter_templates(template, fragment):
    assert fragment in ep.shot_filter(template, 2.0, 1)


def test_shot_filter_index_and_bad_template():
    assert ep.shot_filter('static', 2.0, 3).startswith('[3:v]')
    assert ep.shot_filter('static', 2.0, 3).endswith('[v3]')
    with pytest.raises(ValueError):
        ep.shot_filter('карусель', 2.0, 0)


# ── титри ─────────────────────────────────────────────────────────────

def test_title_filter():
    t = ep.title_filter('Обʼєм 57 мл', 1.0, 3.5)
    assert t.startswith("drawtext=text='Обʼєм 57 мл'") and '\n' not in t
    assert 'fontsize=64' in t and 'y=h-360' in t
    assert "enable='between(t,1.00,3.50)'" in t


def test_title_filter_escaping():
    t = ep.title_filter("Ціна: 100% з'їдає", 0.0, 1.0)
    assert "\\:" in t and "\\%" in t and "\\'" in t


@pytest.mark.parametrize('position,y', [('top', 'y=240'), ('center', 'y=(h-text_h)/2')])
def test_title_positions(position, y):
    assert y in ep.title_filter('текст', 0.0, 1.0, position=position)


@pytest.mark.parametrize('kw', [{'position': 'збоку'}, {'start': 2.0, 'end': 1.0},
                                {'start': 1.0, 'end': 1.0}])
def test_title_filter_validation(kw):
    args = {'start': 0.0, 'end': 1.0}
    args.update(kw)
    with pytest.raises(ValueError):
        ep.title_filter('текст', args.pop('start'), args.pop('end'), **args)


# ── план кадрів ───────────────────────────────────────────────────────

def test_plan_shots_rotation():
    shots = ep.plan_shots(['a.jpg', 'b.jpg', 'c.jpg', 'd.jpg'], [2.0, 2.0, 2.0, 2.0])
    assert [s['template'] for s in shots] == ['zoom_in', 'pan_right', 'zoom_out', 'zoom_in']
    assert [s['index'] for s in shots] == [0, 1, 2, 3]
    assert shots[0]['image'] == 'a.jpg' and shots[0]['duration'] == 2.0


def test_plan_shots_custom_templates():
    shots = ep.plan_shots(['a.jpg', 'b.jpg', 'c.jpg'], [1.0, 1.0, 1.0], templates=['static'])
    assert [s['template'] for s in shots] == ['static'] * 3


@pytest.mark.parametrize('args', [
    (['a.jpg'], [1.0, 2.0], None), ([], [], None), (['a.jpg'], [1.0], []),
    (['a.jpg'], [1.0], ['карусель']),
])
def test_plan_shots_validation(args):
    images, durations, templates = args
    with pytest.raises(ValueError):
        ep.plan_shots(images, durations, templates)


# ── граф ──────────────────────────────────────────────────────────────

def shots2():
    return ep.plan_shots(['a.jpg', 'b.jpg'], [2.0, 3.0])


def test_filtergraph_plain():
    g = ep.build_filtergraph(shots2())
    assert '[v0][v1]concat=n=2:v=1:a=0[vcat]' in g
    assert g.endswith('[vcat]null[vout]')
    assert g.count(';') == 3


def test_filtergraph_with_titles_and_srt():
    g = ep.build_filtergraph(shots2(), titles=[('Перший', 0.0, 2.0), ('Другий', 2.0, 5.0, 'top')],
                             srt='/s.srt')
    assert '[vcat]drawtext' in g and g.count('drawtext') == 2
    assert '[vtxt]' in g and 'y=240' in g
    assert "subtitles=/s.srt:force_style='Fontsize=18,Outline=2'[vout]" in g
    assert '[vtxt]subtitles=' in g


def test_filtergraph_srt_without_titles():
    g = ep.build_filtergraph(shots2(), srt='/s.srt')
    assert '[vcat]subtitles=/s.srt' in g and g.endswith('[vout]')
    assert 'null[vout]' not in g


def test_filtergraph_single_shot_and_empty():
    g = ep.build_filtergraph(ep.plan_shots(['a.jpg'], [2.0]))
    assert '[v0]concat=n=1:v=1:a=0[vcat]' in g
    with pytest.raises(ValueError):
        ep.build_filtergraph([])


# ── команда ───────────────────────────────────────────────────────────

def test_command_silent():
    c = ep.command(['a.jpg', 'b.jpg'], [2.0, 3.0], '/out.mp4')
    assert c[:2] == ['ffmpeg', '-y'] and c[-1] == '/out.mp4'
    assert c.count('-loop') == 2 and c[c.index('-i') + 1] == 'a.jpg'
    assert '-t' in c and '2.000' in c and '3.000' in c
    assert c[c.index('-map') + 1] == '[vout]'
    assert '-shortest' not in c and '-c:v' in c and 'yuv420p' in c


def test_command_with_voice_only():
    c = ep.command(['a.jpg'], [2.0], '/o.mp4', audio='/voice.mp3')
    assert '/voice.mp3' in c and '-shortest' in c
    assert c[c.index('-map', c.index('-map') + 1) + 1] == '1:a'
    assert 'amix' not in ' '.join(c)


def test_command_with_voice_and_music():
    c = ep.command(['a.jpg', 'b.jpg'], [2.0, 2.0], '/o.mp4', audio='/voice.mp3',
                   music='/bg.mp3', srt='/s.srt')
    graph = c[c.index('-filter_complex') + 1]
    assert '[2:a]volume=1[a0];[3:a]volume=0.12[a1];[a0][a1]amix=inputs=2:duration=first[aout]' in graph
    assert c[c.index('-map', c.index('-map') + 1) + 1] == '[aout]'
    assert '-shortest' in c


def test_command_music_only():
    c = ep.command(['a.jpg'], [2.0], '/o.mp4', music='/bg.mp3')
    assert 'amix' not in ' '.join(c)
    assert c[c.index('-map', c.index('-map') + 1) + 1] == '1:a'
