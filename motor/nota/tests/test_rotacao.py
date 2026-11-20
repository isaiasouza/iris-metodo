"""Rotação como tipo de câmera e direção do movimento em graus."""
from __future__ import annotations

import unittest

import presets
import segmentos
from tests.test_lote1 import sidecar
from tests.test_preferencias import padrao

CAM = presets.PADRAO["camera"]


class TestEtiqueta(unittest.TestCase):
    def test_rotacao_vira_tipo(self):
        tipo, conf = segmentos.etiqueta_camera([0.0] * 8, [0.0] * 8, [0.0] * 8, [0.0] * 8, CAM, rot=[8.0] * 8)
        self.assertEqual(tipo, "rotacao")
        self.assertGreater(conf, 0)

    def test_rotacao_pequena_continua_parada(self):
        tipo, _ = segmentos.etiqueta_camera([0.0] * 8, [0.0] * 8, [0.0] * 8, [0.0] * 8, CAM, rot=[0.5] * 8)
        self.assertEqual(tipo, "parada")

    def test_mao_passando_na_frente_nao_vira_rotacao(self):
        # Tripé com ~2 s de giro falso (mão na frente): a mediana fica em 0, a média não.
        rot = [0.0] * 40 + [-40.0] * 8
        z = [0.0] * 48
        self.assertEqual(segmentos.etiqueta_camera(z, z, z, z, CAM, rot=rot)[0], "parada")

    def test_sem_rot_comportamento_antigo(self):
        self.assertEqual(segmentos.etiqueta_camera([-0.05] * 8, [0.0] * 8, [0.0] * 8, [0.0] * 8, CAM)[0], "pan_esq")

    def test_limiares_da_camera_precisam_ser_positivos(self):
        for chave in ("pan_min", "zoom_min", "rot_min"):
            for ruim in (0, -1.0, "2", True, None):
                with self.assertRaises(ValueError, msg=f"{chave}={ruim!r}"):
                    padrao(camera={chave: ruim})
        padrao(camera={"pan_min": 0.03, "zoom_min": 1, "rot_min": 3.5})

    def test_tipo_existe_e_rot_min_no_padrao(self):
        self.assertIn("rotacao", segmentos.TIPOS_CAMERA)
        self.assertEqual(CAM["rot_min"], 2.0)


class TestDirecao(unittest.TestCase):
    def test_quatro_sentidos(self):
        d = segmentos.direcao_camera
        self.assertAlmostEqual(d([0.05] * 4, [0.0] * 4, "pan_dir"), 0.0)
        self.assertAlmostEqual(d([0.0] * 4, [-0.05] * 4, "tilt_cima"), 90.0)
        self.assertAlmostEqual(d([-0.05] * 4, [0.0] * 4, "pan_esq"), 180.0)
        self.assertAlmostEqual(d([0.0] * 4, [0.05] * 4, "tilt_baixo"), 270.0)

    def test_diagonal(self):
        self.assertAlmostEqual(segmentos.direcao_camera([0.05] * 4, [-0.05] * 4, "pan_dir"), 45.0)

    def test_quase_zero_nao_vira_360(self):
        for dy in (-1e-9, 1e-9):
            self.assertEqual(segmentos.direcao_camera([0.05] * 4, [dy] * 4, "pan_dir"), 0.0)

    def test_sem_direcao(self):
        for tipo in ("parada", "mao", "rotacao", "push_in", "pull_out"):
            self.assertIsNone(segmentos.direcao_camera([0.05] * 4, [0.0] * 4, tipo))


class TestTrecho(unittest.TestCase):
    def test_trecho_com_rotacao_e_direcao(self):
        sc = sidecar("A.MP4", n=40)
        sc["quadros"]["cam_rot"] = [8.0] * 40
        trechos, _ = segmentos.trechos_do_clipe(sc, padrao())
        self.assertEqual(trechos[0]["camera"]["tipo"], "rotacao")
        self.assertIsNone(trechos[0]["direcao"])

    def test_pan_tem_direcao_e_campo(self):
        sc = sidecar("A.MP4", n=40)
        sc["quadros"]["cam_dx"] = [-0.05] * 40
        trechos, _ = segmentos.trechos_do_clipe(sc, padrao(campos={"marcador_nome": "{camera} {direcao}"}))
        self.assertEqual(trechos[0]["direcao"], 180.0)
        self.assertEqual(trechos[0]["marcador"]["nome"], "pan_esq 180°")

    def test_analise_antiga_sem_cam_rot(self):
        trechos, _ = segmentos.trechos_do_clipe(sidecar("A.MP4", n=40), padrao())
        self.assertEqual(trechos[0]["camera"]["tipo"], "parada")
        self.assertEqual(segmentos.valores_trecho(trechos[0])["direcao"], "—")

    def test_filtro_e_comportamento_aceitam_rotacao(self):
        sc = sidecar("A.MP4", n=40)
        sc["quadros"]["cam_rot"] = [8.0] * 40
        self.assertEqual(segmentos.montar_selects([sc], padrao(), cameras=["parada"])["trechos"], [])
        self.assertTrue(segmentos.montar_selects([sc], padrao(), cameras=["rotacao"])["trechos"])
        self.assertEqual(segmentos.montar_selects([sc], padrao(camera_comportamento={"rotacao": "excluir"}))["trechos"], [])


if __name__ == "__main__":
    unittest.main()
