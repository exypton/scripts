<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Config Changes - {{ inventory_hostname }}</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        h1 { margin-bottom: 30px; }
        details { margin-bottom: 15px; padding: 10px; border: 1px solid #ddd; border-radius: 5px; }
        summary { font-weight: bold; cursor: pointer; font-size: 16px; }
        .changed { color: orange; }
        .added { color: green; }
        .deleted { color: red; }
        .moved { color: blue; }
    </style>
</head>
<body>

<h1>CHANGES FOR DEVICE: {{ inventory_hostname }}</h1>

<h2 class="changed">Changed Values</h2>
{% if xml_diff.changed %}
    {% for item in xml_diff.changed %}
        <details>
            <summary>▶ {{ item.path }}</summary>
            <p><b>OLD:</b> {{ item.old }}</p>
            <p><b>NEW:</b> {{ item.new }}</p>
        </details>
    {% endfor %}
{% else %}
    <p>No changed elements.</p>
{% endif %}

<h2 class="added">Added Elements</h2>
{% if xml_diff.added %}
    {% for item in xml_diff.added %}
        <details>
            <summary>▶ {{ item }}</summary>
            <p>ACTION: added</p>
        </details>
    {% endfor %}
{% else %}
    <p>No added elements.</p>
{% endif %}

<h2 class="deleted">Deleted Elements</h2>
{% if xml_diff.deleted %}
    {% for item in xml_diff.deleted %}
        <details>
            <summary>▶ {{ item }}</summary>
            <p>ACTION: removed</p>
        </details>
    {% endfor %}
{% else %}
    <p>No removed elements.</p>
{% endif %}

<h2 class="moved">Moved Elements</h2>
{% if xml_diff.moved %}
    {% for item in xml_diff.moved %}
        <details>
            <summary>▶ {{ item }}</summary>
            <p>ACTION: moved</p>
        </details>
    {% endfor %}
{% else %}
    <p>No moved elements.</p>
{% endif %}

</body>
</html>
