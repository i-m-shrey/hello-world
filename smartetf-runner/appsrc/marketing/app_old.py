from flask import Flask, render_template

app = Flask(__name__)

@app.route('/')
def index():
    # You can add dynamic data here later if needed
    return render_template('index.html')

@app.route('/contact')
def contact():
    return render_template('contact.html')

if __name__ == '__main__':
    app.run(debug=True)
