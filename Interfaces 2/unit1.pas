unit Unit1;

{$mode objfpc}{$H+} // Activa programación orientada a objetos de Free Pascal y cadenas AnsiStrings largas

interface

uses
  Classes, SysUtils, Forms, Controls, Graphics, Dialogs, StdCtrls, ExtCtrls,
  ComCtrls, TAGraph, TASeries, TACustomSeries, LazSerial, fphttpclient, fpjson,
  jsonparser;

type

  { TForm1 }

  TForm1 = class(TForm)
    Bar1: TBarSeries;            // Serie de barras que dibuja el Histograma de 6 canales
    CB1: TCheckBox;              // CheckBox "Envía": habilita la retransmisión HTTP hacia Flask
    CB_COM: TCheckBox;          // CheckBox "COM On/Off": abre o cierra el descriptor de puerto serie
    ChartAmbiental: TChart;      // Contenedor visual del gráfico de dispersión temporal (líneas)
    ChartHisto: TChart;          // Contenedor visual del gráfico de distribución de partículas (barras)
    Hr: TLabel;                  // Display numérico de gran tamaño para Humedad Relativa
    LblHrTitulo: TLabel;         // Etiqueta fija "Hu Re"
    LblSensores: TLabel;         // Cabecera de estado "[ Sensores OnLine ]"
    LblTempTitulo: TLabel;       // Etiqueta fija "Temp"
    MySer: TLazSerial;           // Componente no visual para comunicación serie asíncrona
    PanelAutor: TPanel;          // Panel superior de firma "By Alberto Caro - 2023"
    PanelMP: TPanel;             // Contenedor de selección de canales de partículas
    PanelTempBox: TPanel;        // Marco delimitador visual para los displays numéricos
    PanelUMA: TPanel;            // Panel contenedor de los selectores de estación
    RB_MP01: TRadioButton;       // Selector para resaltar la serie PM 1.0
    RB_MP10: TRadioButton;       // Selector para resaltar la serie PM 10
    RB_MP25: TRadioButton;       // Selector para resaltar la serie PM 2.5
    RB_UMA1: TRadioButton;       // Selector de visualización para estación UMA 1
    RB_UMA2: TRadioButton;       // Selector de visualización para estación UMA 2
    RB_UMA3: TRadioButton;       // Selector de visualización para estación UMA 3
    RB_UMA4: TRadioButton;       // Selector de visualización para estación UMA 4
    RB_UMA5: TRadioButton;       // Selector de visualización para estación UMA 5
    SB1: TStatusBar;             // Barra de estado: Panel 0 = Fecha/Hora, Panel 1 = Trama cruda
    Serie1: TLineSeries;         // Serie lineal roja: PM 1.0 ug/m3
    Serie2: TLineSeries;         // Serie lineal azul: PM 2.5 ug/m3
    Serie3: TLineSeries;         // Serie lineal verde: PM 10 ug/m3
    Te: TLabel;                  // Display numérico de gran tamaño para Temperatura
    TimerReloj: TTimer;          // Reloj de sistema (intervalo 1000 ms) para la fecha y hora
    procedure CB_COMChange(Sender: TObject);
    procedure FormClose(Sender: TObject; var CloseAction: TCloseAction);
    procedure FormCreate(Sender: TObject);
    procedure MySerRxData(Sender: TObject);
    procedure RBUmaClick(Sender: TObject);
    procedure TimerRelojTimer(Sender: TObject);
  private
    procedure Clear_Trama;
    procedure Send_Data_To_Flask(aAux: Array of Integer);
  public

  end;

var
  Form1: TForm1;
  // Arreglos dinámicos en memoria para almacenar las 12 muestras visibles de cada serie
  aMP01 : Array[0..11] of Integer; // Ventana deslizante de PM 1.0
  aMP25 : Array[0..11] of Integer; // Ventana deslizante de PM 2.5
  aMP10 : Array[0..11] of Integer; // Ventana deslizante de PM 10
  // Arreglo para almacenar los valores puntuales de los 6 tamaños del histograma
  aHisto: Array[0..05] of Integer;
  // Paleta de colores indexada para cada una de las 6 barras del histograma
  aClr  : Array[0..5]  of TColor;
  // Identificador de la estación seleccionada actualmente por el usuario (1 a 5)
  nID   : Byte;
  lFlask: Boolean;

implementation

{$R *.lfm} // Vincula el archivo de recursos de la interfaz de diseño visual

{ TForm1 }

// ==============================================================================
// INICIALIZACIÓN DE LA APLICACIÓN
// ==============================================================================
procedure TForm1.FormCreate(Sender: TObject);
begin
  // Por defecto monitoreamos la estación UMA 1
  nID := 1;
  lFlask := False;

  // Asignación de colores cromáticos para las 6 columnas del Histograma:
  // 0.3um = Rojo, 0.5um = Verde, 1.0um = Azul, 2.5um = Amarillo, 5.0um = Lima, 10um = Celeste
  aClr[0] := clRed;
  aClr[1] := clGreen;
  aClr[2] := clBlue;
  aClr[3] := clYellow;
  aClr[4] := clLime;
  aClr[5] := RGBToColor(173, 216, 230);

  // Inicializa las estructuras en cero y limpia los lienzos de los gráficos
  Clear_Trama;

  // Fuerza la primera actualización visual del reloj en la barra de estado
  TimerRelojTimer(nil);
end;

// ==============================================================================
// REINICIALIZACIÓN Y VACIADO DE SERIES (BUFFER GRÁFICO)
// ==============================================================================
procedure TForm1.Clear_Trama;
var
  nPos: Integer;
begin
  // Limpia los puntos existentes en la memoria visual de TAChart
  Serie1.Clear;
  Serie2.Clear;
  Serie3.Clear;
  Bar1.Clear;

  // Rellena los arreglos con valor base 0 y dibuja los 12 puntos iniciales
  for nPos := 0 to 11 do
  begin
    aMP01[nPos] := 0;
    aMP25[nPos] := 0;
    aMP10[nPos] := 0;
    Serie1.AddXY(nPos, aMP01[nPos]);
    Serie2.AddXY(nPos, aMP25[nPos]);
    Serie3.AddXY(nPos, aMP10[nPos]);
  end;

  // Rellena y dibuja las 6 barras base en cero respetando su color asignado
  for nPos := 0 to 5 do
  begin
    aHisto[nPos] := 0;
    Bar1.AddXY(nPos, aHisto[nPos], '', aClr[nPos]);
  end;
end;

// ==============================================================================
// SERIALIZACIÓN JSON Y DESPACHO HTTP POST AL SERVIDOR FLASK
// ==============================================================================
procedure TForm1.Send_Data_To_Flask(aAux: Array of Integer);
var
  Data: TJSONObject;         // Estructura DOM de Free Pascal para componer el JSON
  sResp: String;             // Almacena la respuesta textual devuelta por el servidor
  ClienteHTTP: TFPHttpClient; // Objeto para el manejo de sockets HTTP nativo
  BodyStream: TStringStream;  // Flujo en memoria para transportar el cuerpo de la petición
begin
  // 1. Instanciación del objeto JSON
  Data := TJSONObject.Create();
  try
    // Mapeo clave-valor de cada elemento recibido en la trama serial:
    Data.Add('id', aAux[0]);     // ID de la estación UMA
    Data.Add('mp01', aAux[1]);   // PM 1.0 ug/m3
    Data.Add('mp02', aAux[2]);   // PM 2.5 ug/m3
    Data.Add('mp03', aAux[3]);   // PM 10 ug/m3
    Data.Add('hi01', aAux[4]);   // 0.3 um
    Data.Add('hi02', aAux[5]);   // 0.5 um
    Data.Add('hi03', aAux[6]);   // 1.0 um
    Data.Add('hi04', aAux[7]);   // 2.5 um
    Data.Add('hi05', aAux[8]);   // 5.0 um
    Data.Add('hi06', aAux[9]);   // 10 um
    Data.Add('te', aAux[10]);    // Temperatura (°C)
    Data.Add('hr', aAux[11]);    // Humedad Relativa (%)

    // 2. Creación del cliente HTTP y preparación del flujo de bytes
    ClienteHTTP := TFPHttpClient.Create(Nil);
    BodyStream := TStringStream.Create(Data.AsJSON);
    try
      // Encabezado vital: declara al backend que el contenido es application/json
      ClienteHTTP.AddHeader('Content-Type', 'application/json');
      ClienteHTTP.RequestBody := BodyStream;

      try
        // Emisión síncrona de la petición POST hacia el endpoint del backend
        sResp := ClienteHTTP.Post('http://127.0.0.1:7070/data');
      except
        // Control de tolerancia a fallos: si Flask no está corriendo, no congelamos la UI
        CB1.Checked := False; // Desactiva el envío automático
        SB1.Panels[1].Text := 'Aviso: Servidor Flask inalcanzable en puerto 7070';
      end;

    finally
      // Liberación de recursos para prevenir fugas de memoria (Memory Leaks)
      BodyStream.Free;
      ClienteHTTP.Free;
    end;

  finally
    Data.Free; // Destrucción del objeto JSON en el Heap
  end;
end;

// ==============================================================================
// INTERRUPCIÓN POR LLEGADA DE DATOS SERIALES (EVENTO OnRxData)
// ==============================================================================
procedure TForm1.MySerRxData(Sender: TObject);
var
  aAux: Array[0..11] of Integer; // Contenedor temporal de la trama parseada
  sLine, sPaq: String;
  nI, nPos: Byte;
begin
  // Lectura directa del buffer de recepción de TLazSerial
  sLine := Trim(MySer.ReadData);
  if sLine = '' then Exit;

  // Sanitización: si se reciben caracteres de salto de línea pegados, cortamos en el primero
  if Pos(#10, sLine) > 0 then
    sLine := Trim(Copy(sLine, 1, Pos(#10, sLine) - 1));

  sPaq := sLine; // Preservamos una copia de la cadena cruda para la barra de estado

  try
    // Algoritmo de Tokenización CSV:
    // Itera buscando comas, extrae la subcadena previa, la castea a Integer y la borra de sLine.
    for nI := 0 to 10 do
    begin
      nPos := Pos(',', sLine);
      if nPos = 0 then Exit; // Si la trama llegó cortada o con ruido, se descarta
      aAux[nI] := StrToInt(Copy(sLine, 1, nPos - 1));
      Delete(sLine, 1, nPos);
    end;
    // El residuo final corresponde al dato de Humedad Relativa
    aAux[11] := StrToInt(Trim(sLine));
  except
    // Ante cualquier error de conversión (StrToInt), salimos limpiamente sin abortar la app
    Exit;
  end;

  // Filtro de estación: únicamente procesamos si la trama pertenece a la UMA seleccionada
  if aAux[0] = nID then
  begin
    // 1. Envío opcional a Flask si el usuario tiene activa la casilla "Envía"
    if CB1.Checked then Send_Data_To_Flask(aAux);

    // 2. Reflejo de la trama cruda en el Panel 1 de la barra de estado
    SB1.Panels[1].Text := 'Data : ' + sPaq;

    // 3. Actualización de los indicadores textuales grandes
    Te.Caption := IntToStr(aAux[10]);
    Hr.Caption := IntToStr(aAux[11]);

    // 4. Limpieza de series para el redibujado de la nueva escena gráfica
    Serie1.Clear;
    Serie2.Clear;
    Serie3.Clear;
    Bar1.Clear;

    // 5. Renderizado del Histograma: lee los índices [4..9] de aAux
    for nPos := 0 to 5 do
    begin
      aHisto[nPos] := aAux[nPos + 4];
      Bar1.AddXY(nPos, aHisto[nPos], '', aClr[nPos]);
    end;

    // 6. Algoritmo de Desplazamiento Temporal (Scrolling Data Left):
    // Se asigna la lectura fresca en la última posición visible (índice 10)
    aMP01[10] := aAux[1];
    aMP25[10] := aAux[2];
    aMP10[10] := aAux[3];

    // Se grafican los puntos actuales y se corre el valor hacia la izquierda (nPos + 1)
    for nPos := 0 to 10 do
    begin
      Serie1.AddXY(nPos, aMP01[nPos]);
      Serie2.AddXY(nPos, aMP25[nPos]);
      Serie3.AddXY(nPos, aMP10[nPos]);

      // Desplazamiento de memoria del arreglo:
      aMP01[nPos] := aMP01[nPos + 1];
      aMP25[nPos] := aMP25[nPos + 1];
      aMP10[nPos] := aMP10[nPos + 1];
    end;
  end;
end;

// ==============================================================================
// GESTIÓN DEL PUERTO SERIE (BOTÓN ON/OFF)
// ==============================================================================
procedure TForm1.CB_COMChange(Sender: TObject);
begin
  try
    if CB_COM.Checked then
      MySer.Open  // Conecta y escucha sobre el puerto configurado (COM2)
    else
      MySer.Close; // Cierra el socket/puerto del sistema operativo
  except
    on E: Exception do
    begin
      CB_COM.Checked := False;
      ShowMessage('Error al abrir ' + MySer.Device + ': ' + E.Message);
    end;
  end;
end;

// ==============================================================================
// CONMUTACIÓN DE ESTACIÓN AMBIENTAL (UMA 1 A 5)
// ==============================================================================
procedure TForm1.RBUmaClick(Sender: TObject);
begin
  // Asignación de la variable global nID según el RadioButton activo
  if RB_UMA1.Checked then nID := 1
  else if RB_UMA2.Checked then nID := 2
  else if RB_UMA3.Checked then nID := 3
  else if RB_UMA4.Checked then nID := 4
  else if RB_UMA5.Checked then nID := 5;

  // Al cambiar de estación se vacía la pantalla para esperar datos frescos de la UMA elegida
  Clear_Trama;
end;

// ==============================================================================
// RELOJ DEL SISTEMA (ACTUALIZACIÓN CADA 1000 MS)
// ==============================================================================
procedure TForm1.TimerRelojTimer(Sender: TObject);
begin
  SB1.Panels[0].Text := 'Fecha : ' + FormatDateTime('dd-mm-yyyy', Now) +
                        ' - Hora : ' + FormatDateTime('hh:nn:ss', Now);
end;

// ==============================================================================
// CIERRE DESTRUCTOR LIMPIO DEL FORMULARIO
// ==============================================================================
procedure TForm1.FormClose(Sender: TObject; var CloseAction: TCloseAction);
begin
  // Libera el recurso hardware del puerto serie si la app se cierra inesperadamente
  if MySer.Active then
    MySer.Close;
end;

end.