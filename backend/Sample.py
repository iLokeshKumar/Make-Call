from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

class Product:
    def __init__(self, name, price):
        self.name = name
        self.price = price

class QuoteItem:
    def __init__(self, product, quantity):
        self.product = product
        self.quantity = quantity

    def total_price(self):
        return self.product.price * self.quantity


def generate_pdf(quote_items, filename="quote.pdf"):
    c = canvas.Canvas(filename, pagesize=letter)
    width, height = letter

    y = height - 50

    c.setFont("Helvetica", 12)
    c.drawString(50, y, "Product Quote")
    y -= 30

    total_amount = 0

    for item in quote_items:
        line = f"{item.product.name} - {item.quantity} x {item.product.price} = {item.total_price()}"
        c.drawString(50, y, line)
        y -= 20
        total_amount += item.total_price()

    y -= 20
    c.drawString(50, y, f"Total: {total_amount}")

    c.save()


# Example usage
p1 = Product("Laptop", 50000)
p2 = Product("Mouse", 500)

item1 = QuoteItem(p1, 2)
item2 = QuoteItem(p2, 3)

generate_pdf([item1, item2])