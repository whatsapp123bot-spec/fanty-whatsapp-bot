from django.test import TestCase

from .services import answer_from_persona


class PersonaDeterministicTests(TestCase):
	def setUp(self):
		self.persona = {
			'name': 'Luna',
			'trade_name': 'Tienda Sol',
			'legal_name': 'Sol S.A.C.',
			'phone': '+51 999 888 777',
			'whatsapp_link': 'https://wa.me/51999888777',
			'website': 'https://tiendasol.pe',
			'catalog_url': 'https://tiendasol.pe/catalogo',
			'instagram': 'https://instagram.com/tiendasol',
			'facebook': 'https://facebook.com/tiendasol',
			'tiktok': '',
			'yape_number': '999888777',
			'yape_holder': 'Sol SAC',
			'yape_alias': 'SOL',
			'plin_number': '',
			'card_brands': 'Visa, MasterCard',
			'card_provider': 'Culqi',
			'card_paylink': 'https://pago.sol/abc',
			'districts_costs': 'Miraflores S/10\nSurco S/8',
			'typical_delivery_time': '24-48h',
			'free_shipping_from': 'S/199',
			'boleta_yes': 'Sí',
			'factura_yes': 'Sí',
		}

	def test_identity(self):
		res = answer_from_persona('¿Quién eres?', self.persona, brand='Tienda Sol')
		self.assertIn('Luna', res)
		self.assertIn('Tienda Sol', res)

	def test_yape(self):
		res = answer_from_persona('¿Tienen yape?', self.persona, brand='Tienda Sol')
		self.assertIn('Yape', res)
		self.assertIn('999888777', res)
		self.assertIn('Sol', res)

	def test_envios(self):
		res = answer_from_persona('¿Hacen envíos?', self.persona, brand='Tienda Sol')
		self.assertIn('Miraflores', res)
		self.assertIn('Tiempo típico', res)

	def test_goodbye_offers_socials(self):
		res = answer_from_persona('gracias, nos vemos', self.persona, brand='Tienda Sol')
		# Si hay redes, debe incluir alguna
		self.assertTrue(('Instagram' in res) or ('Facebook' in res))

