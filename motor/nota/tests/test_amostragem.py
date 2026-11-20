from __future__ import annotations

import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

import amostragem
from amostragem import ErroLeitura, InfoClipe, _duracao, _ultima_mensagem, altura_reduzida, amostrar, probe
from tests import sinteticos


class TestAmostragem(unittest.TestCase):
    def test_probe_le_metadados(self):
        info = probe(sinteticos.clipes()["parado"])
        self.assertEqual((info.largura, info.altura), (1920, 1080))
        self.assertAlmostEqual(info.fps, 24.0, places=2)
        self.assertAlmostEqual(info.duracao, 3.0, delta=0.1)
        self.assertEqual(info.codec, "h264")

    def test_altura_reduzida_e_par_e_proporcional(self):
        info = probe(sinteticos.clipes()["parado"])
        self.assertEqual(altura_reduzida(info, 320), 180)

    def test_amostrar_entrega_quadros_reduzidos_em_cinza(self):
        info = probe(sinteticos.clipes()["parado"])
        quadros = list(amostrar(info, 4.0, 320, hw=False))
        self.assertIn(len(quadros), (12, 13))
        t, q = quadros[1]
        self.assertAlmostEqual(t, 0.25)
        self.assertEqual(q.shape, (180, 320))
        self.assertEqual(q.dtype, np.uint8)

    def test_arquivo_invalido_gera_erro_de_leitura(self):
        with tempfile.TemporaryDirectory() as d:
            ruim = Path(d) / "ruim.mp4"
            ruim.write_bytes(b"isto nao e video")
            with self.assertRaises(ErroLeitura):
                probe(str(ruim))

    def test_video_girado_fica_em_pe(self):
        info = probe(sinteticos.girado())
        self.assertEqual((info.largura, info.altura), (1080, 1920))
        q = next(iter(amostrar(info, 4.0, 320, hw=False)))[1]
        self.assertGreater(q.shape[0], q.shape[1])
        self.assertEqual(q.shape, (568, 320))


class TestMensagemDeErro(unittest.TestCase):
    def test_pula_repeticoes_e_linhas_vazias(self):
        texto = "[h264 @ 0x1] erro de verdade\n    Last message repeated 5 times\n\n  \n"
        self.assertEqual(_ultima_mensagem(texto), "[h264 @ 0x1] erro de verdade")

    def test_so_repeticoes_ou_vazio_vira_vazio(self):
        self.assertEqual(_ultima_mensagem("Last message repeated 2 times\n"), "")
        self.assertEqual(_ultima_mensagem(""), "")

    def test_mensagem_da_decodificacao_incompleta_usa_a_linha_util(self):
        codigo = ("import sys; sys.stdout.buffer.write(bytes(576 * 3)); "
                  "sys.stderr.write('pacote corrompido\\n    Last message repeated 9 times\\n')")
        with _falso_ffmpeg(codigo):
            terminou, n, erro = _consumir_em_thread(INFO_FALSA)
        self.assertIsInstance(erro, ErroLeitura)
        self.assertIn("pacote corrompido", str(erro))
        self.assertNotIn("repeated", str(erro))


class TestDuracao(unittest.TestCase):
    def test_prefere_a_do_stream_de_video(self):
        # O formato (container) pode ser mais longo por causa do áudio; a contagem de quadros é do vídeo.
        self.assertEqual(_duracao({"format": {"duration": "12.5"}, "streams": [{"duration": "10.0"}]}), 10.0)

    def test_stream_sem_duracao_cai_para_a_do_formato(self):
        self.assertEqual(_duracao({"format": {"duration": "12.5"}, "streams": [{"duration": "N/A"}]}), 12.5)
        self.assertEqual(_duracao({"format": {"duration": "12.5"}, "streams": [{}]}), 12.5)

    def test_formato_na_cai_para_a_do_stream(self):
        self.assertEqual(_duracao({"format": {"duration": "N/A"}, "streams": [{"duration": "7.25"}]}), 7.25)

    def test_sem_duracao_usa_quadros_sobre_fps(self):
        dados = {"format": {}, "streams": [{"duration": "N/A", "nb_frames": "240", "avg_frame_rate": "24/1"}]}
        self.assertEqual(_duracao(dados), 10.0)

    def test_desconhecida_vira_zero(self):
        dados = {"format": {"duration": "N/A"}, "streams": [{"nb_frames": "N/A", "avg_frame_rate": "0/0"}]}
        self.assertEqual(_duracao(dados), 0.0)


def _falso_ffmpeg(codigo: str):
    """Troca o comando do ffmpeg por um script Python (simula decodificador problemático)."""
    return mock.patch.object(amostragem, "_comando", lambda *a, **k: [sys.executable, "-c", codigo])


def _consumir_em_thread(info, limite_s=20.0):
    """Consome amostrar() numa thread; devolve (terminou, quadros, erro) sem travar a suíte."""
    res = {"quadros": 0, "erro": None}

    def alvo():
        try:
            for _ in amostrar(info, 4.0, 32, hw=False):
                res["quadros"] += 1
        except ErroLeitura as e:
            res["erro"] = e

    th = threading.Thread(target=alvo, daemon=True)
    th.start()
    th.join(limite_s)
    return not th.is_alive(), res["quadros"], res["erro"]


INFO_FALSA = InfoClipe("/x/falso.mp4", 3.0, 24.0, 32, 18, "h264")  # 32x18 -> quadro 32x18 = 576 bytes


class TestDecodificacaoProblematica(unittest.TestCase):
    def test_stderr_grande_nao_trava(self):
        # >64 KB de erros antes dos quadros: com stderr em pipe lido só no fim, o ffmpeg trava.
        codigo = ("import sys; sys.stderr.write('erro de decodificacao\\n' * 20000); sys.stderr.flush(); "
                  "sys.stdout.buffer.write(bytes(576 * 12))")
        with _falso_ffmpeg(codigo):
            terminou, n, erro = _consumir_em_thread(INFO_FALSA)
        self.assertTrue(terminou, "amostrar travou com stderr grande")
        self.assertEqual(n, 12)
        self.assertIsNone(erro)

    def test_ffmpeg_pendurado_estoura_o_tempo(self):
        codigo = "import time; time.sleep(60)"
        inicio = time.monotonic()
        with _falso_ffmpeg(codigo), mock.patch.object(amostragem, "_TEMPO_MIN_S", 1.0, create=True), \
                mock.patch.object(amostragem, "_FATOR_TEMPO", 0.0, create=True):
            terminou, n, erro = _consumir_em_thread(INFO_FALSA)
        self.assertTrue(terminou, "amostrar não matou o ffmpeg pendurado")
        self.assertLess(time.monotonic() - inicio, 15.0)
        self.assertIsInstance(erro, ErroLeitura)
        self.assertIn("tempo", str(erro))

    def test_codigo_de_saida_nao_zero_e_erro(self):
        codigo = "import sys; sys.stdout.buffer.write(bytes(576 * 12)); sys.stderr.write('quebrou'); sys.exit(1)"
        with _falso_ffmpeg(codigo):
            terminou, n, erro = _consumir_em_thread(INFO_FALSA)
        self.assertTrue(terminou)
        self.assertIsInstance(erro, ErroLeitura)
        self.assertIn("quebrou", str(erro))

    def test_decodificacao_incompleta_e_erro(self):
        # 3 s a 4 amostras/s = 12 quadros esperados; só 3 saem e o ffmpeg termina "bem".
        codigo = "import sys; sys.stdout.buffer.write(bytes(576 * 3))"
        with _falso_ffmpeg(codigo):
            terminou, n, erro = _consumir_em_thread(INFO_FALSA)
        self.assertTrue(terminou)
        self.assertIsInstance(erro, ErroLeitura)
        self.assertIn("incompleta", str(erro))
        self.assertIn("3 de 12", str(erro))

    def test_duracao_desconhecida_nao_exige_contagem(self):
        info = InfoClipe("/x/falso.mp4", 0.0, 24.0, 32, 18, "h264")
        codigo = "import sys; sys.stdout.buffer.write(bytes(576 * 3))"
        with _falso_ffmpeg(codigo):
            terminou, n, erro = _consumir_em_thread(info)
        self.assertTrue(terminou)
        self.assertEqual(n, 3)
        self.assertIsNone(erro)


if __name__ == "__main__":
    unittest.main()
