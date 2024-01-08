
function XML_HTTP()
{
    var xmlhttp;

    if (window.XMLHttpRequest)
      {// code for IE7+, Firefox, Chrome, Opera, Safari
      xmlhttp=new XMLHttpRequest();
      }
    else
      {// code for IE6, IE5
      xmlhttp=new ActiveXObject("Microsoft.XMLHTTP");
      }
    return xmlhttp;
}

function state_changed_callback()
{
    if (this.readyState==4 && this.status==200)
        this.data_received_callback();
}

function data_received_callback()
{
        var c = this.data_receiver;
        this.data_receiver= null;
        var parsed = null;
        var error = false;
        try         {   
                        parsed = JSON.parse(this.responseText); 
                    }
        catch(err)  {
                        error = true;
                        if( c.data_error )
                        {   c.data_error(this, "JSON parse error"); }
                    }

        if( !error )
            c.data_received(parsed);
}

function XMLRequest(url, receiver, cacheable)
{
    var http_request = XML_HTTP();
    http_request.data_receiver = receiver;
    http_request.data_received_callback = data_received_callback;
    http_request.onreadystatechange = state_changed_callback;
    if( !cacheable )
    {
        if( url.indexOf("?") < 0 )
            url += "?_=" + Math.random();
        else
            url += "&_=" + Math.random();
    }
    http_request.open("GET", url, true);
    http_request.send();
    return http_request;
}            



function format_columns(columns_labels)
{
    this.columns_labels = columns_labels;
    
    this.format_data_table = function(data)
    {
        var cols = [{"id":"T", "label":"Time", "type":"datetime"}];
        for ( cl of this.columns_labels )
        {
            cols.push({
                "id":cl["column"],  "label":cl["label"], "type":"number"
            })
        }
        var dt = new google.visualization.DataTable(
            {
                "cols": cols, 
                rows:[]
            });
        for( tup of data )
        {
            var t = eval("new " + tup["t"]);
            var row = [t];
            for( cl of this.columns_labels )
                row.push(tup[cl["column"]]);
            dt.addRow(row);
        }
        return dt;
    }
    
    return this;
}

function translate_label(x, mapping)
{
    var out = null;
    if( typeof mappng === "function")
        out = mapping(x);
    else
        out = mapping[x];
    return out == null ? x : out;
}

function formatter_by_label(field_name, label_mapping)
{
    var split = field_name.split("/");
    this.field_name = split[0];                 // without "[*]", which is implied
    this.field_agg = split[1];
    this.label_mapping = (label_mapping == null) ? {} : label_mapping;
    this.columns = [this.field_name+"[*]/"+this.field_agg];
    
    this.make_data_table = function(data)
    {
        var cols = [{"id":"T", "label":"Time", "type":"datetime"}];
        var in_labels = data["labels_for_names"][this.field_name];
        for( l of in_labels )
        {
            var legend = translate_label(l, this.label_mapping);
            cols.push({
                "id": l,
                "label": legend,
                "type": "number"
            })
        }

        var rows = [];
        
        for( in_row of data.data )
        {
            var new_row = [new Date(in_row["t"]*1000)];
            for( l of in_labels )
            {
                var key = this.field_name + "[" + l + "]" + "/" + this.field_agg;
                new_row.push(in_row[key]);
            }
            rows.push(new_row);
        }
        
        
        // format the data table
        var dt = new google.visualization.DataTable(
            {
                "cols": cols, 
                "rows": []
            }
        );
        
        dt.addRows(rows);
        return dt;
    }
    
    return this;
}

function formatter_by_name(fields)
{
    //
    // fields: list of dicts:
    // [{
    //      "column": "name[label]/agg",
    //      "label": "chart label"              // if missing, label = column
    //  },
    //  ...
    //  ]
    //
    
    this.spec_to_legend_mapping = fields;
    this.field_specs = Object.keys(fields);
    this.columns = this.field_specs;
    
    this.make_data_table = function(data)
    {
        var cols = [{"id":"T", "label":"Time", "type":"datetime"}];
        for( fs of this.field_specs )
        {
            var legend = translate_label(fs, this.spec_to_legend_mapping);
            cols.push({
                "id": fs,
                "label": legend,
                "type": "number"
            })
        }

        var rows = [];
        
        for( in_row of data.data )
        {
            var new_row = [new Date(in_row["t"]*1000)];
            for( fs of this.field_specs )
            {
                new_row.push(in_row[fs])
            }
            rows.push(new_row);
        }
        
        
        // format the data table
        var dt = new google.visualization.DataTable(
            {
                "cols": cols, 
                "rows": []
            }
        );
        
        dt.addRows(rows);
        
        return dt;
    }
    
    return this;
}

function chart(element, options, formatter, type)
{
    this.options = options;
    this.formatter = formatter;
    
    if ( type == "stepped" )
        this.chart_object = new google.visualization.SteppedAreaChart(document.getElementById(element));
    else
        this.chart_object = new google.visualization.LineChart(document.getElementById(element));
    
    this.query_columns = function()
    {
        return this.formatter.columns;
    }
    
    this.data_received = function(data)
    {
        var t0 = data.minT;
        var t1 = data.maxT;
        if ( t0 != null )
        {
            var ha = this.options.hAxis;
            if ( ha == null )
            {
                ha = {};
                this.options.hAxis = ha;
            }
            ha.minValue = new Date(t0*1000);
            ha.maxValue = new Date(t1*1000);
        }

        var dt = this.formatter.make_data_table(data);
        this.chart_object.draw(dt, this.options);
    }

    return this;
}

